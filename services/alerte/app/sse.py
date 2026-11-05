"""Diffusion en direct (Server-Sent Events) : du bus vers les clients connectés (MS-11).

SSE plutôt que WebSocket : la diffusion va dans un seul sens, elle passe par HTTP (la passerelle et
le contrat OpenAPI la décrivent sans extension), et le navigateur ou `fetch` la relit seul. Le
contrat note la limite : `EventSource` ne pose pas d'en-tête `Authorization`, le tableau de bord lit
donc le flux avec `fetch` (`frontend/src/services/alertStream.ts`).

Le lecteur Kafka tourne dans un fil, les clients dans la boucle d'événements : `EventHub.publish`
est appelable depuis n'importe quel fil et dépose le message dans la file de chaque client par
`call_soon_threadsafe`. Un client dont la file déborde est **coupé** (jamais de mémoire sans
borne) : il se reconnecte et relit la liste des alertes, qui fait foi.

Format d'un message : `event: alert.state_changed`, `id: <id de l'événement>`, `data: <JSON>`. Les
données sont celles de l'événement du bus (schéma `Alert` du contrat, plus `previous_state`). Un
message `heartbeat` part toutes les `heartbeat_s` secondes : une connexion morte se voit.
"""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.model import utc_stamp

logger = logging.getLogger("app.sse")

ALERT_EVENT = "alert.state_changed"
HEARTBEAT = "heartbeat"
RETRY_MS = 3000  # délai de reconnexion conseillé au client


@dataclass(frozen=True)
class Message:
    event: str
    data: dict[str, Any]
    event_id: str | None = None

    def encode(self) -> bytes:
        lines = [f"event: {self.event}"]
        if self.event_id:
            lines.append(f"id: {self.event_id}")
        lines.append("data: " + json.dumps(self.data, ensure_ascii=False, separators=(",", ":")))
        return ("\n".join(lines) + "\n\n").encode("utf-8")


class Subscription:
    def __init__(self, hub: "EventHub", types: frozenset[str] | None, size: int) -> None:
        self._hub = hub
        self.types = types
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[Message | None] = asyncio.Queue(maxsize=size)
        self.overflowed = False

    def offer(self, message: Message) -> None:  # appelé dans la boucle du client
        if self.types is not None and message.event not in self.types:
            return
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed = True
            self._hub.unsubscribe(self)
            logger.warning(
                "client SSE coupé : file pleine", extra={"fields": {"counter": "sse_dropped"}}
            )
            while not self.queue.empty():  # le client est trop lent : on jette son retard...
                self.queue.get_nowait()
            self.queue.put_nowait(None)  # ... et on lui signale la fin du flux

    def close(self) -> None:
        self._hub.unsubscribe(self)


class EventHub:
    def __init__(self, queue_size: int = 200) -> None:
        self._queue_size = queue_size
        self._subscriptions: set[Subscription] = set()
        self._lock = threading.Lock()

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    def subscribe(self, types: frozenset[str] | None = None) -> Subscription:
        """À appeler dans la boucle d'événements du client."""
        subscription = Subscription(self, types, self._queue_size)
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)

    def publish(self, message: Message) -> int:
        """Dépose `message` chez chaque client ; rend le nombre de clients visés. Tout fil."""
        with self._lock:
            targets = list(self._subscriptions)
        for subscription in targets:
            try:
                subscription.loop.call_soon_threadsafe(subscription.offer, message)
            except RuntimeError:  # boucle fermée : le client est parti
                self.unsubscribe(subscription)
        return len(targets)

    def on_bus_message(self, raw: bytes) -> None:
        """Un message de `alerts.events` : diffusé tel quel s'il est lisible, ignoré sinon."""
        try:
            event = json.loads(raw)
            data = event["data"]
            event_id = event["id"]
        except (ValueError, KeyError, TypeError):
            logger.warning("message de alerts.events illisible, ignoré")
            return
        self.publish(Message(ALERT_EVENT, data, event_id))


async def stream(
    hub: EventHub, types: frozenset[str] | None, heartbeat_s: float
) -> AsyncIterator[bytes]:
    """Les octets SSE d'un client, jusqu'à sa déconnexion (l'annulation arrive par le générateur).

    L'abonnement précède le premier octet : quand le client lit `: connecté`, il est inscrit, et
    aucun événement postérieur ne lui échappe (il peut alors lire la liste des alertes sans trou).
    """
    subscription = hub.subscribe(types)
    try:
        yield f"retry: {RETRY_MS}\n: connecté\n\n".encode()
        while True:
            try:
                message = await asyncio.wait_for(subscription.queue.get(), timeout=heartbeat_s)
            except TimeoutError:
                now = utc_stamp(datetime.now(UTC))
                yield Message(HEARTBEAT, {"time": now}).encode()
                continue
            if message is None:  # coupé : file pleine
                return
            yield message.encode()
    finally:
        subscription.close()
