"""Un identifiant d'essai unique, un producteur Kafka et les fabriques de travailleur et d'API."""

import secrets

import pytest

from tests.integration import stack
from tests.integration.harness import Api, SseClient, Worker


@pytest.fixture
def run_id():
    """Identifiant unique de l'essai : ses alertes et événements se retrouvent par lui."""
    identifier = f"it-{secrets.token_hex(4)}"
    yield identifier
    stack.erase(identifier)


@pytest.fixture
def kafka():
    producer = stack.producer()
    yield producer
    producer.close()


@pytest.fixture
def start_worker():
    """`start_worker()` : un travailleur dans son propre groupe (relit tout depuis le début)."""
    started: list[Worker] = []

    def start(group: str | None = None, **kwargs) -> Worker:
        worker = Worker(group or f"alerte-it-{secrets.token_hex(4)}", **kwargs)
        started.append(
            worker
        )  # avant le démarrage : un échec d'affectation ne laisse aucun fil orphelin
        return worker.start()

    yield start
    for worker in started:
        worker.close()


@pytest.fixture
def api(monkeypatch):
    server = Api(monkeypatch).start()
    yield server
    server.close()


@pytest.fixture
def start_client(api):
    clients: list[SseClient] = []

    def start(role: str = "viewer", types: str | None = None) -> SseClient:
        client = SseClient(api, role, types).start()
        clients.append(client)
        return client

    yield start
    for client in clients:
        client.close()
