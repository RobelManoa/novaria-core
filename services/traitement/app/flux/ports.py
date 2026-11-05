"""Ce que le processeur demande au monde extérieur (architecture hexagonale, comme la collecte).

Chaque port a un adaptateur réel (`adapters/`) et une doublure en mémoire dans les tests.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .episodes import EpisodeRecord


class PublishFailed(Exception):
    """Le broker n'a pas accusé réception (indisponible, délai dépassé, message refusé)."""


class StoreFailed(Exception):
    """Une base n'a pas répondu ou a refusé l'écriture."""


@dataclass(frozen=True)
class Record:
    """Un message lu sur `iot.raw`."""

    key: bytes | None
    value: bytes
    partition: int
    offset: int


class EventPublisher(Protocol):
    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        """Met le message en file d'envoi ; `flush` attend les accusés de réception."""

    def flush(self) -> None:
        """Rend quand tout ce qui a été publié est accusé ; lève `PublishFailed` sinon."""


class RejectArchive(Protocol):
    def insert(self, document: dict) -> None:
        """Copie dans MongoDB `rejects` (`_id` fixé : un rejeu n'ajoute rien) ; `StoreFailed`."""


class EpisodeStore(Protocol):
    def upsert(self, record: EpisodeRecord) -> None:
        """Écrit l'épisode dans `dwh.fact_congestion_episode` (unicité : tronçon, run, début)."""


class StatsStore(Protocol):
    def add(
        self, kind: str, window_start: datetime, road_segment_id: str | None, counts: dict[str, int]
    ) -> None:
        """Ajoute les compteurs au document (`kind`, `window_start`, tronçon) de MongoDB."""
