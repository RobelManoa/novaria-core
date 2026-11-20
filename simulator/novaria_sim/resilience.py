"""Reprises avec attente croissante et disjoncteur vers une dépendance (MS-16).

Bibliothèque standard seulement : ce fichier est **le même** dans la collecte et dans le simulateur
(`simulator/novaria_sim/resilience.py`) ; un test vérifie qu'ils sont identiques.

- `retry` : au plus `attempts` essais, attente de `base_s`, puis ×`factor`, plafonnée à `max_s`,
  avec une part aléatoire (`jitter`) pour que des clients qui échouent ensemble ne reviennent pas
  ensemble. Seules les erreurs de `retry_on` sont rejouées : une erreur de logique ne l'est jamais.
- `CircuitBreaker` : après `failure_threshold` échecs **de suite**, le disjoncteur s'ouvre et les
  appels échouent aussitôt (`CircuitOpen`), sans attendre le délai de la dépendance ; au bout de
  `reset_timeout_s`, UN appel d'essai passe (état « semi-ouvert ») : s'il réussit le disjoncteur se
  referme, sinon il se rouvre pour un nouveau délai.

```
fermé --échecs de suite >= seuil--> ouvert --délai écoulé--> semi-ouvert --succès--> fermé
                                       ^------------- échec de l'essai ------------'
```

Un `observer(événement, **champs)` optionnel reçoit `call` (issue ok ou error, durée), `rejected`,
`state` (changement d'état) et `retry` : c'est lui qui alimente `/metrics` et le journal.
"""

import random
import threading
import time
from collections.abc import Callable
from typing import Any

CLOSED, HALF_OPEN, OPEN = "closed", "half_open", "open"
STATE_VALUE = {CLOSED: 0, HALF_OPEN: 1, OPEN: 2}
Observer = Callable[..., None]


class CircuitOpen(Exception):
    """Le disjoncteur est ouvert : la dépendance n'a pas été appelée."""

    def __init__(self, name: str, retry_in_s: float) -> None:
        super().__init__(f"disjoncteur « {name} » ouvert (nouvel essai dans {retry_in_s:.0f} s)")
        self.name, self.retry_in_s = name, retry_in_s


def backoff_delays(
    attempts: int,
    base_s: float = 0.1,
    factor: float = 2.0,
    max_s: float = 2.0,
    jitter: float = 0.2,
    rng: Callable[[], float] = random.random,  # noqa: S311 - dispersion des reprises, pas de sécurité
) -> list[float]:
    """Les attentes entre `attempts` essais (donc `attempts - 1` valeurs)."""
    delays = []
    for rank in range(max(attempts - 1, 0)):
        delay = min(base_s * factor**rank, max_s)
        delays.append(delay * (1 + jitter * (2 * rng() - 1)))
    return delays


def retry(
    function: Callable[[], Any],
    *,
    attempts: int = 3,
    base_s: float = 0.1,
    factor: float = 2.0,
    max_s: float = 2.0,
    jitter: float = 0.2,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    never_retry: tuple[type[BaseException], ...] = (),
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,  # noqa: S311
    observer: Observer | None = None,
    name: str = "",
) -> Any:
    """Appelle `function`, la rejoue après une attente croissante tant qu'il reste des essais."""
    delays = backoff_delays(attempts, base_s, factor, max_s, jitter, rng)
    for attempt in range(1, attempts + 1):
        try:
            return function()
        except never_retry:
            raise
        except retry_on as error:
            if attempt == attempts:
                raise
            if observer:
                observer(
                    "retry",
                    name=name,
                    attempt=attempt,
                    delay_s=delays[attempt - 1],
                    error=type(error).__name__,
                )
            sleep(delays[attempt - 1])
    raise AssertionError("inatteignable")  # pragma: no cover


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        reset_timeout_s: float = 15.0,
        trip_on: tuple[type[BaseException], ...] = (Exception,),
        clock: Callable[[], float] = time.monotonic,
        observer: Observer | None = None,
    ) -> None:
        if failure_threshold < 1 or reset_timeout_s <= 0:
            raise ValueError("seuil d'échecs et délai de reprise doivent être positifs")
        self.name = name
        self._threshold, self._reset_s, self._trip_on = failure_threshold, reset_timeout_s, trip_on
        self._clock, self._observer = clock, observer
        self._lock = threading.Lock()
        self._state, self._failures, self._opened_at, self._trial_running = CLOSED, 0, 0.0, False

    @property
    def state(self) -> str:
        with self._lock:
            return self._current()

    def _current(self) -> str:
        if self._state == OPEN and self._clock() - self._opened_at >= self._reset_s:
            self._move(HALF_OPEN)
        return self._state

    def _move(self, state: str) -> None:
        if state != self._state:
            before, self._state = self._state, state
            if self._observer:
                self._observer(
                    "state", name=self.name, before=before, after=state, failures=self._failures
                )

    def call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            state = self._current()
            if state == OPEN or (state == HALF_OPEN and self._trial_running):
                wait = max(self._reset_s - (self._clock() - self._opened_at), 0.0)
                if self._observer:
                    self._observer("rejected", name=self.name)
                raise CircuitOpen(self.name, wait)
            if state == HALF_OPEN:
                self._trial_running = True
        started = self._clock()
        try:
            result = function(*args, **kwargs)
        except self._trip_on:
            self._observe("error", started)
            with self._lock:
                self._trial_running = False
                self._failures += 1
                if self._state == HALF_OPEN or self._failures >= self._threshold:
                    self._opened_at = self._clock()
                    self._move(OPEN)
            raise
        except BaseException:
            with (
                self._lock
            ):  # une erreur de logique n'est ni un succès ni un échec de la dépendance
                self._trial_running = False
            raise
        self._observe("ok", started)
        with self._lock:
            self._trial_running = False
            self._failures = 0
            self._move(CLOSED)
        return result

    def _observe(self, outcome: str, started: float) -> None:
        if self._observer:
            self._observer(
                "call", name=self.name, outcome=outcome, duration_s=self._clock() - started
            )
