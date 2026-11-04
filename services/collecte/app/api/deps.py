"""Assemblage du service d'ingestion à partir de la configuration (une instance par processus).

Les connexions (Kafka, MongoDB) sont créées à la première utilisation et fermées à l'arrêt. Sans
`MONGO_URL`, les écritures lèvent `StoreFailed` : le service démarre, répond à sa sonde, et refuse
chaque mesure en 503 plutôt que de la perdre.
"""

import threading
from dataclasses import dataclass, field

from app.adapters.kafka_publisher import KafkaEventPublisher
from app.adapters.mongo_store import MongoCollections, MongoRawEvents, MongoRejects
from app.core.config import Settings, get_settings
from app.services.ingestion import IngestionService, StoreFailed


class NotConfiguredStore:
    """Stockage absent : toute opération échoue (503), aucune mesure n'est acceptée sans copie."""

    def exists(self, event_id: str) -> bool:
        raise StoreFailed("MONGO_URL n'est pas configuré")

    def insert(self, document: dict) -> bool:
        raise StoreFailed("MONGO_URL n'est pas configuré")


@dataclass
class Components:
    service: IngestionService
    closers: list = field(default_factory=list)

    def close(self) -> None:
        for close in self.closers:
            close()


def build_components(settings: Settings) -> Components:
    publisher = KafkaEventPublisher(
        settings.kafka_bootstrap_servers, timeout_s=settings.kafka_publish_timeout_s
    )
    closers = [publisher.close]
    if settings.mongo_url is None:
        raw_events, rejects = NotConfiguredStore(), NotConfiguredStore()
    else:
        collections = MongoCollections(
            settings.mongo_url.get_secret_value(),
            settings.mongo_db,
            timeout_ms=settings.mongo_timeout_ms,
        )
        raw_events, rejects = MongoRawEvents(collections), MongoRejects(collections)
        closers.append(collections.close)
    service = IngestionService(publisher, raw_events, rejects, max_bytes=settings.max_body_bytes)
    return Components(service, closers)


_components: Components | None = None
_lock = threading.Lock()


def get_components() -> Components:
    global _components  # noqa: PLW0603 - une seule instance par processus, créée à la demande
    if _components is None:
        with _lock:
            if _components is None:
                _components = build_components(get_settings())
    return _components


def get_ingestion_service() -> IngestionService:
    return get_components().service


def close_components() -> None:
    global _components  # noqa: PLW0603
    with _lock:
        components, _components = _components, None
    if components is not None:
        components.close()
