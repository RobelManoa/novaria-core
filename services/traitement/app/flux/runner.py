"""Boucle du service de flux : lire, traiter, publier, valider.

À chaque tour : lecture d'un lot, traitement message par message, publication des fenêtres
fermées (`tick` pour un flux silencieux), puis `checkpoint` (accusés du broker, statistiques) et
validation des offsets. Toute panne d'une dépendance **arrête** le service : aucun offset n'est
validé, le conteneur redémarre et relit à partir du dernier offset sûr (idempotence en aval).
"""

import logging
import threading
from pathlib import Path
from typing import Protocol

from .ports import Record

logger = logging.getLogger("app.flux")


class Worker(Protocol):
    """Ce que la boucle demande à un service : le flux et le pipeline d'écriture en sont deux."""

    def handle(
        self, raw: bytes, key: bytes | None, partition: int | None, offset: int | None
    ) -> None: ...

    def tick(self) -> None: ...

    def checkpoint(self) -> dict[int, int]: ...


class Source(Protocol):
    def poll(self, timeout_ms: int = ...) -> list[Record]: ...

    def commit(self, offsets: dict[int, int]) -> None: ...


def beat(path: str) -> None:
    """Marque le service vivant (sonde du conteneur) ; une erreur d'écriture n'arrête rien."""
    try:
        Path(path).touch()
    except OSError:
        logger.warning("fichier de vie non écrit")


def run(
    processor: Worker,
    source: Source,
    stop: threading.Event,
    *,
    poll_timeout_ms: int = 1000,
    heartbeat_file: str | None = None,
) -> int:
    """Rend le nombre de messages traités. S'arrête quand `stop` est levé."""
    handled = 0
    committed: dict[int, int] = {}
    while not stop.is_set():
        records = source.poll(poll_timeout_ms)
        for record in records:
            processor.handle(record.value, record.key, record.partition, record.offset)
        handled += len(records)
        processor.tick()
        offsets = processor.checkpoint()
        if offsets != committed:
            source.commit(offsets)
            committed = dict(offsets)
        if heartbeat_file:
            beat(heartbeat_file)
    return handled
