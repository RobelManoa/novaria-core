"""Boucle du travailleur : lire les indicateurs, évaluer, publier, notifier, valider (MS-11).

À chaque tour : un lot d'indicateurs est traité (alertes créées ou résolues, événements dans la
boîte d'envoi) ; les offsets sont validés **dès que** les événements sont en base (la boîte d'envoi
les garde) ; puis le relais publie, le notificateur remet les alertes CREATED, et le relais publie
une seconde fois les NOTIFIED. L'événement CREATED part donc avant la notification, qui peut être
lente.

Toute panne d'une dépendance (base, bus) **arrête** la boucle : aucun offset n'est validé pour le
lot en cours, le conteneur redémarre et relit à partir du dernier offset sûr. Rejouer un indicateur
est sans effet : l'index unique et la recherche de l'alerte ouverte rendent chaque décision
idempotente.
"""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.adapters.kafka_io import Record
from app.domain.model import Rule
from app.services.ingestion import IndicatorHandler
from app.services.notifier import Notifier
from app.services.ports import AlertStore
from app.services.relay import OutboxRelay

logger = logging.getLogger("app.worker")


class RulesCache:
    """Les règles lues en base, gardées `ttl_s` secondes : un changement d'API agit vite."""

    def __init__(
        self, store: AlertStore, ttl_s: float, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._store = store
        self._ttl_s = ttl_s
        self._monotonic = monotonic
        self._rules: list[Rule] = []
        self._read_at: float | None = None

    def get(self) -> list[Rule]:
        now = self._monotonic()
        if self._read_at is None or now - self._read_at >= self._ttl_s:
            self._rules = self._store.rules()
            self._read_at = now
        return self._rules


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
    handler: IndicatorHandler,
    source: Source,
    relay: OutboxRelay,
    notifier: Notifier,
    stop: threading.Event,
    *,
    poll_timeout_ms: int = 200,
    heartbeat_file: str | None = None,
) -> int:
    """Rend le nombre de messages traités. S'arrête quand `stop` est levé."""
    handled = 0
    while not stop.is_set():
        records = source.poll(poll_timeout_ms)
        offsets: dict[int, int] = {}
        for record in records:
            handler.handle(record.value, record.key)
            offsets[record.partition] = max(offsets.get(record.partition, 0), record.offset + 1)
        handled += len(records)
        if offsets:
            source.commit(offsets)
        relay.run_once()
        if notifier.run_once():
            relay.run_once()
        if heartbeat_file:
            beat(heartbeat_file)
    return handled
