"""File d'envoi des événements en mémoire : le contrôleur ne dépend jamais du bus.

Une décision du contrôleur (un changement d'état, un refus) dépose son événement ici, **sans
attendre Kafka**. Un fil d'envoi (`worker/dispatch.py`) publie ensuite, attend l'accusé du broker et
retente. Si le bus est en panne, les feux continuent de tourner ; les événements attendent, dans
l'ordre, jusqu'à `maxlen` (au-delà, les plus anciens sont abandonnés et comptés).
"""

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Outgoing:
    topic: str
    key: str | None
    value: bytes
    event_id: str
    audit: dict[str, Any] | None = None  # l'entrée d'audit à écrire une fois l'événement parti


class Outbox:
    def __init__(self, maxlen: int = 10_000) -> None:
        self._items: deque[Outgoing] = deque()
        self._maxlen = maxlen
        self._lock = threading.Lock()
        self.dropped = 0

    def put(self, item: Outgoing) -> None:
        with self._lock:
            if len(self._items) >= self._maxlen:
                self._items.popleft()
                self.dropped += 1
            self._items.append(item)

    def take(self, limit: int) -> list[Outgoing]:
        with self._lock:
            return [self._items.popleft() for _ in range(min(limit, len(self._items)))]

    def give_back(self, items: list[Outgoing]) -> None:
        """Remet en tête, dans l'ordre d'origine, ce qui n'a pas pu partir."""
        with self._lock:
            self._items.extendleft(reversed(items))

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
