"""Un service d'ingestion sur le vrai Kafka et le vrai MongoDB, et un identifiant d'essai unique."""

import secrets

import pytest
from fastapi.testclient import TestClient

from app.adapters.kafka_publisher import KafkaEventPublisher
from app.adapters.mongo_store import MongoCollections, MongoRawEvents, MongoRejects
from app.api.deps import get_ingestion_service
from app.main import app
from app.services.ingestion import IngestionService
from tests.integration import stack


def new_service(*, max_bytes: int = 65536):
    """Un service et ses fermetures : à chaque appel de nouvelles connexions (une « instance »)."""
    publisher = KafkaEventPublisher(stack.BOOTSTRAP, timeout_s=15)
    collections = MongoCollections(stack.MONGO_URL, stack.database_name(), timeout_ms=5000)
    service = IngestionService(
        publisher, MongoRawEvents(collections), MongoRejects(collections), max_bytes=max_bytes
    )
    return service, [publisher.close, collections.close]


@pytest.fixture
def run_id():
    """Identifiant unique de l'essai : ses messages, rejets et traces se retrouvent par lui."""
    identifier = f"it-{secrets.token_hex(4)}"
    yield identifier
    stack.erase(identifier)


@pytest.fixture
def real_service():
    service, closers = new_service()
    yield service
    for close in closers:
        close()


@pytest.fixture
def http(real_service):
    app.dependency_overrides[get_ingestion_service] = lambda: real_service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
