"""Câblage du service, configuration et arrêt propre (MS-08)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.deps as deps
from app.adapters.mongo_store import MongoRawEvents, MongoRejects
from app.core.config import Settings
from app.main import app
from app.services.ingestion import PublishFailed, StoreFailed
from tests.support import body, measurement


@pytest.fixture(autouse=True)
def clean_components():
    deps.close_components()
    yield
    deps.close_components()


# --- Configuration ----------------------------------------------------------------------------


def test_the_defaults_start_closed_and_without_secret():
    settings = Settings()
    assert settings.kafka_bootstrap_servers == ""
    assert settings.mongo_url is None
    assert settings.max_body_bytes == 65536
    assert settings.mongo_db == "novaria"


def test_the_connections_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.setenv("MONGO_URL", "mongodb://svc_collecte:motdepasse@mongo:27017/novaria")
    monkeypatch.setenv("MONGO_DB", "autre")
    settings = Settings()
    assert settings.kafka_bootstrap_servers == "kafka:9092"
    assert settings.mongo_db == "autre"
    assert "motdepasse" not in repr(settings)
    assert "motdepasse" not in settings.model_dump_json()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MAX_BODY_BYTES", "10"),
        ("MAX_BODY_BYTES", "99999999"),
        ("KAFKA_PUBLISH_TIMEOUT_S", "0"),
        ("KAFKA_PUBLISH_TIMEOUT_S", "600"),
        ("MONGO_TIMEOUT_MS", "5"),
    ],
)
def test_absurd_limits_are_refused_at_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_a_secret_in_a_refused_value_is_never_written_in_the_error():
    """Un type refusé pour `MONGO_URL` : sans `hide_input_in_errors`, la valeur serait recopiée."""
    with pytest.raises(ValidationError) as error:
        Settings(mongo_url=["mongodb://svc:motdepasse-secret@mongo/db"])
    assert "motdepasse-secret" not in str(error.value)
    assert "MONGO_URL" in str(error.value).upper()


def test_a_refused_url_is_never_written_in_the_error():
    with pytest.raises(ValidationError) as error:
        Settings(mongo_url="mongodb://x:motdepasse-secret@h/db", max_body_bytes=1)
    assert "motdepasse-secret" not in str(error.value)


# --- Câblage ----------------------------------------------------------------------------------


def test_without_mongodb_configured_every_measurement_is_refused_in_503_not_lost(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    service = deps.get_ingestion_service()
    with pytest.raises(StoreFailed, match="MONGO_URL"):
        service.receive(body(measurement(0)))


def test_without_kafka_configured_a_measurement_is_refused_after_the_duplicate_check(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://u:p@127.0.0.1:1/db")
    monkeypatch.setenv("MONGO_TIMEOUT_MS", "100")
    components = deps.build_components(Settings())
    assert isinstance(components.service._raw_events, MongoRawEvents)
    assert isinstance(components.service._rejects, MongoRejects)
    with pytest.raises(PublishFailed):
        components.service._publisher.publish("iot.raw", "INT_01", b"{}")


def test_the_not_configured_store_refuses_every_operation():
    store = deps.NotConfiguredStore()
    with pytest.raises(StoreFailed):
        store.exists("a")
    with pytest.raises(StoreFailed):
        store.insert({"id": "a"})


def test_the_components_are_built_once_per_process_and_closed_on_demand():
    first = deps.get_components()
    assert deps.get_components() is first
    closed = []
    first.closers.append(lambda: closed.append(True))
    deps.close_components()
    assert closed == [True]
    deps.close_components()  # une seconde fermeture ne fait rien
    assert closed == [True]
    assert deps.get_components() is not first


def test_the_application_closes_its_connections_when_it_stops():
    closed = []
    deps.get_components().closers.append(lambda: closed.append(True))
    with TestClient(app):
        assert closed == []
    assert closed == [True]


def test_the_real_route_answers_503_when_nothing_is_configured():
    """Aucune variable : le service démarre, répond à sa sonde, et refuse proprement les mesures."""
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.post("/api/v1/measurements", content=body(measurement(0)))
    assert response.status_code == 503
    assert response.json()["code"] == "UPSTREAM_UNAVAILABLE"
