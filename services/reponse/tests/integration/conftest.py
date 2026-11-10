"""Un carrefour d'essai unique, un producteur Kafka et des fabriques de service."""

import pytest

from app.core.config import get_settings
from tests.integration import stack
from tests.integration.harness import Service, new_intersection


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    """La clé est dans l'environnement avant tout démarrage : le masquage des journaux lit les
    réglages dès le premier message, et les garderait en mémoire sans elle."""
    monkeypatch.setenv("JWT_SECRET", stack.JWT_SECRET)
    get_settings.cache_clear()


@pytest.fixture
def intersection():
    """Un carrefour à soi ; ses traces d'audit sont effacées à la fin de l'essai."""
    name = new_intersection()
    yield name
    stack.erase(name)


@pytest.fixture
def kafka():
    producer = stack.producer()
    yield producer
    producer.close()


@pytest.fixture
def make_service(kafka):
    """`make_service(*intersections, **options)` : un service démarré, arrêté à la fin."""
    started: list[Service] = []

    def make(*intersections: str, warm: bool = True, **options) -> Service:
        service = Service(intersections, **options)
        started.append(service)  # avant le démarrage : un échec ne laisse aucun fil orphelin
        service.start()
        if warm:
            service.warm_up(kafka)
        return service

    yield make
    for service in started:
        service.close()
