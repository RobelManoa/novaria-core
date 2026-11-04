"""Limitation du débit de la connexion (BE-08) : fonctions et classes pures, sans HTTP.

Deux protections complémentaires, parce qu'aucune ne suffit seule :
- par adresse du client : `login_attempts_per_minute` essais, tous comptes confondus. Elle freine
  celui qui essaie beaucoup de comptes depuis un poste (bourrage d'identifiants) ;
- par identifiant : `login_max_failures` échecs sur une fenêtre glissante de `login_lockout_s`
  secondes ; une fois la limite atteinte, la connexion à ce compte est refusée (même avec le bon mot
  de passe) jusqu'à ce que le plus ancien échec sorte de la fenêtre. Elle freine celui qui
  s'acharne sur un compte depuis plusieurs adresses. Un identifiant **inconnu** est compté comme
  un autre : la réponse 429 ne dit pas si le compte existe. Un succès remet le compteur à zéro.

Limites assumées (documentées dans `docs/04-devsecops/securite-applicative.md`) :
- l'état est dans la mémoire du processus : un redémarrage le remet à zéro, et N répliques ou N
  processus multiplient les essais permis par N. En production il faut le dupliquer en amont
  (passerelle, pare-feu applicatif) ou le déplacer dans un magasin partagé ;
- la mémoire est bornée (`MAX_KEYS`) : au-delà, les clés les plus anciennes sont oubliées.
"""

import hashlib
import ipaddress
import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable

MAX_KEYS = 10_000
IP_WINDOW_S = 60


class RateLimited(Exception):
    """Trop d'essais : le client doit attendre `retry_after_s` secondes."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"réessayer dans {retry_after_s} s")
        self.retry_after_s = retry_after_s


class SlidingWindow:
    """Au plus `limit` événements par clé sur les `window_s` dernières secondes."""

    def __init__(
        self,
        limit: int,
        window_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = MAX_KEYS,
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _live(self, key: str, now: float) -> deque[float]:
        events = self._events.get(key)
        if events is None:
            return deque()
        while events and events[0] <= now - self.window_s:
            events.popleft()
        if not events:
            del self._events[key]
            return deque()
        self._events.move_to_end(key)
        return events

    def _remember(self, key: str, now: float) -> None:
        events = self._live(key, now)
        events.append(now)
        self._events[key] = events
        self._events.move_to_end(key)
        while len(self._events) > self._max_keys:
            self._events.popitem(last=False)  # la clé la moins récemment vue

    def _wait(self, events: deque[float], now: float) -> int:
        """Secondes avant que le plus ancien événement sorte de la fenêtre.

        Toujours au moins 1 : `_live` a retiré les événements sortis, donc le reste est > 0.
        """
        return math.ceil(events[0] + self.window_s - now)

    def retry_after(self, key: str) -> int:
        """0 si la clé est sous la limite ; sinon, secondes à attendre. Ne compte rien."""
        with self._lock:
            now = self._clock()
            events = self._live(key, now)
            return self._wait(events, now) if len(events) >= self.limit else 0

    def attempt(self, key: str) -> int:
        """Compte un essai s'il est permis (rend 0) ; sinon rend les secondes à attendre."""
        with self._lock:
            now = self._clock()
            events = self._live(key, now)
            if len(events) >= self.limit:
                return self._wait(events, now)
            self._remember(key, now)
            return 0

    def record(self, key: str) -> None:
        with self._lock:
            self._remember(key, self._clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def __len__(self) -> int:
        return len(self._events)


def account_key(username: str) -> str:
    """Clé d'un identifiant : empreinte de sa forme normalisée (casse et espaces sans effet)."""
    return hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()


def forwarded_address(peer: str | None, forwarded_for: str | None, hops: int) -> str | None:
    """Adresse du client, derrière `hops` relais de confiance.

    Chaque relais ajoute l'adresse de son interlocuteur à droite de `X-Forwarded-For` : l'entrée de
    confiance est donc la `hops`-ième en partant de la droite ; celles de gauche viennent du client
    et se falsifient. À `hops == 0` l'en-tête est ignoré. Une valeur absente ou illisible rend
    l'adresse de la connexion.
    """
    if hops <= 0 or not forwarded_for:
        return peer
    entries = [entry.strip() for entry in forwarded_for.split(",")]
    if len(entries) < hops:
        return peer
    candidate = entries[-hops]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return peer
    return candidate


def client_key(address: str | None) -> str:
    """Clé d'un client : son adresse ; pour IPv6, son réseau /64 (un poste en a des milliards)."""
    try:
        ip = ipaddress.ip_address(address or "")
    except ValueError:
        return "inconnue"
    if isinstance(ip, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class LoginThrottle:
    """Les deux limites de la connexion, appelées dans cet ordre par la route."""

    def __init__(
        self,
        *,
        attempts_per_minute: int,
        max_failures: int,
        lockout_s: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._by_client = SlidingWindow(attempts_per_minute, IP_WINDOW_S, clock=clock)
        self._failures = SlidingWindow(max_failures, lockout_s, clock=clock)

    def admit(self, address: str | None, username: str) -> None:
        """Lève `RateLimited` si le compte est bloqué ou si le client dépasse son débit."""
        wait = self._failures.retry_after(account_key(username))
        if wait:
            raise RateLimited(wait)
        wait = self._by_client.attempt(client_key(address))
        if wait:
            raise RateLimited(wait)

    def failed(self, username: str) -> None:
        self._failures.record(account_key(username))

    def succeeded(self, username: str) -> None:
        self._failures.reset(account_key(username))
