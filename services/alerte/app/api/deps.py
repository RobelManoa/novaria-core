"""Composants de l'API (base, cycle de vie, diffusion) et dépendances d'authentification.

Les composants sont créés à la demande, une fois par processus. Sans `POSTGRES_URL`, les routes qui
touchent la base répondent 503 (`UPSTREAM_UNAVAILABLE`) au lieu d'empêcher le service de démarrer :
la sonde de santé répond, et l'état se voit. Les tests remplacent ces dépendances par des faux
(`app.dependency_overrides`).
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.adapters.kafka_io import EventsReader
from app.adapters.postgres_store import PostgresAlertStore
from app.core.config import TOPIC_ALERTS, Settings, get_settings
from app.services.alerts import AlertService
from app.services.ports import AlertStore, StoreFailed
from app.sse import EventHub

logger = logging.getLogger("app.deps")


class NotConfiguredStore:
    """Tient la place de la base sans `POSTGRES_URL` : toute utilisation lève `StoreFailed`."""

    def __getattr__(self, name: str) -> Any:
        raise StoreFailed("POSTGRES_URL n'est pas configuré")


@dataclass
class Components:
    store: AlertStore
    service: AlertService
    hub: EventHub
    reader: EventsReader | None = None
    closers: list[Callable[[], None]] = field(default_factory=list)

    def start(self) -> None:
        if self.reader is not None:
            self.reader.start()

    def close(self) -> None:
        if self.reader is not None:
            self.reader.stop()
        for close in self.closers:
            close()


def build_components(settings: Settings) -> Components:
    closers: list[Callable[[], None]] = []
    store: AlertStore
    if settings.dsn:
        pg = PostgresAlertStore(
            settings.dsn, max_size=settings.postgres_pool_max, timeout_s=settings.postgres_timeout_s
        )
        closers.append(pg.close)
        store = pg
    else:
        store = NotConfiguredStore()  # type: ignore[assignment]
    hub = EventHub(settings.sse_queue_size)
    reader = None
    if settings.sse_enabled and settings.kafka_bootstrap_servers:
        reader = EventsReader(settings.kafka_bootstrap_servers, TOPIC_ALERTS, hub.on_bus_message)
    return Components(store, AlertService(store), hub, reader, closers)


_components: Components | None = None
_lock = threading.Lock()


def get_components() -> Components:
    # Une seule instance par processus, créée à la demande.
    global _components  # noqa: PLW0603
    if _components is None:
        with _lock:
            if _components is None:
                _components = build_components(get_settings())
    return _components


def close_components() -> None:
    global _components  # noqa: PLW0603
    with _lock:
        components, _components = _components, None
    if components is not None:
        components.close()


def get_store() -> AlertStore:
    return get_components().store


def get_service() -> AlertService:
    return get_components().service


def get_hub() -> EventHub:
    return get_components().hub
