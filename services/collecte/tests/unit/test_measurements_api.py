"""`POST /api/v1/measurements` : réponses conformes au contrat de la collecte (MS-08)."""

import json

import pytest

from app.api.deps import get_ingestion_service
from app.core.config import get_settings
from app.main import app
from app.services.ingestion import PublishFailed, StoreFailed
from tests.openapi_checks import PROBLEM, RECEIPT, check
from tests.support import body, measurement, with_value

URL = "/api/v1/measurements"


def post(client, payload, **headers):
    raw = payload if isinstance(payload, bytes) else body(payload)
    return client.post(URL, content=raw, headers={"Content-Type": "application/json", **headers})


# --- 202 --------------------------------------------------------------------------------------


def test_a_new_valid_measurement_answers_202_accepted_and_is_on_iot_raw(client, rig):
    event = measurement(0)
    response = post(client, event)
    assert response.status_code == 202
    assert response.json() == {"event_id": event["id"], "status": "ACCEPTED"}
    check(response.json(), RECEIPT)
    assert [e["id"] for e in rig.publisher.events("iot.raw")] == [event["id"]]


def test_the_same_measurement_again_answers_202_duplicate_and_publishes_nothing(client, rig):
    event = measurement(0)
    post(client, event)
    response = post(client, event)
    assert response.status_code == 202
    assert response.json() == {"event_id": event["id"], "status": "DUPLICATE"}
    check(response.json(), RECEIPT)
    assert len(rig.publisher.events("iot.raw")) == 1


def test_the_content_type_is_not_required(client):
    response = client.post(URL, content=body(measurement(0)))
    assert response.status_code == 202


def test_the_response_carries_the_correlation_id_the_caller_gave(client, rig):
    response = post(client, measurement(0), **{"X-Correlation-ID": "corr-du-simulateur"})
    assert response.headers["X-Correlation-ID"] == "corr-du-simulateur"


# --- 422 --------------------------------------------------------------------------------------


def test_an_invalid_measurement_answers_422_with_the_faulty_field_and_goes_to_the_error_topic(
    client, rig
):
    response = post(client, with_value(measurement(0), ("data", "occupancy_rate"), 1.7))
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    check(problem, PROBLEM)
    assert problem["code"] == "VALIDATION_ERROR"
    assert problem["errors"][0]["field"] == "body.data.occupancy_rate"
    assert "CONTRACT_VIOLATION" in problem["detail"]
    assert rig.publisher.events("iot.raw") == []
    (dlq,) = rig.publisher.events("errors.dlq")
    assert dlq["data"]["reason_code"] == "CONTRACT_VIOLATION"
    assert problem["correlation_id"] == response.headers["X-Correlation-ID"]
    assert dlq["correlation_id"] == response.headers["X-Correlation-ID"]


@pytest.mark.parametrize(
    "payload",
    [b"", b"{", b'{"id": 1', b"pas du json", b"\xff\xfe\x00", b"[]", b"null", b'"texte"'],
)
def test_unreadable_or_not_an_object_answers_422_and_is_kept_for_analysis(client, rig, payload):
    response = post(client, payload)
    assert response.status_code == 422
    check(response.json(), PROBLEM)
    assert rig.publisher.events("iot.raw") == []
    assert len(rig.publisher.events("errors.dlq")) == 1
    assert len(rig.rejects.documents) == 1


def with_limit(rig, monkeypatch, limit: int) -> None:
    """La même limite pour la lecture du corps (réglage) et pour la validation (service)."""
    monkeypatch.setenv("MAX_BODY_BYTES", str(limit))
    get_settings.cache_clear()
    rig.service._max_bytes = limit


def test_a_body_over_the_limit_is_refused_after_reading_only_what_is_needed(
    client, rig, monkeypatch
):
    with_limit(rig, monkeypatch, 2048)
    response = post(client, b"x" * 5_000_000)
    assert response.status_code == 422
    problem = response.json()
    check(problem, PROBLEM)
    assert "2048" in problem["errors"][0]["message"]
    (dlq,) = rig.publisher.events("errors.dlq")
    assert dlq["data"]["reason_code"] == "UNREADABLE"
    assert len(dlq["data"]["original_payload"]) <= 20000, "la charge conservée est tronquée"


def test_the_body_is_read_only_until_the_limit_is_exceeded():
    """Un client qui envoie des mégaoctets n'occupe pas la mémoire : lecture arrêtée à la limite."""
    import asyncio

    from app.api.v1.measurements import read_limited

    read = []

    class Stream:
        async def stream(self):
            for _ in range(10_000):
                read.append(1)
                yield b"x" * 1024

    body_read = asyncio.run(read_limited(Stream(), 2048))
    assert len(body_read) == 2049
    assert len(read) == 3, "trois morceaux de 1 Kio suffisent pour dépasser 2 048 octets"


def test_a_body_exactly_at_the_limit_is_read_and_one_byte_more_is_not(client, rig, monkeypatch):
    with_limit(rig, monkeypatch, 1024)
    raw = body(measurement(0))
    raw += b" " * (1024 - len(raw))  # des espaces après le JSON : toujours un JSON valide
    assert len(raw) == 1024
    assert post(client, raw).status_code == 202
    assert post(client, raw + b" ").status_code == 422


def test_at_most_twenty_faulty_fields_are_listed_and_each_message_is_short(client):
    event = measurement(0)
    event["data"].update({f"extra_{i}": 1 for i in range(60)})
    response = post(client, event)
    errors = response.json()["errors"]
    assert response.status_code == 422
    assert len(errors) == 20
    assert all(len(item["message"]) <= 300 for item in errors)


# --- 503 et 500 -------------------------------------------------------------------------------


@pytest.mark.parametrize("error", [PublishFailed("x"), StoreFailed("x")])
def test_a_down_broker_or_database_answers_503_and_the_detail_names_no_address(client, rig, error):
    def broken(*_, **__):
        raise error

    rig.service.receive = broken  # type: ignore[method-assign]
    response = post(client, measurement(0))
    assert response.status_code == 503
    problem = response.json()
    check(problem, PROBLEM)
    assert problem["code"] == "UPSTREAM_UNAVAILABLE"
    assert "renvoyer" in problem["detail"]


def test_an_unexpected_error_answers_500_without_technical_detail_but_with_the_correlation_id(
    client, rig
):
    def broken(*_, **__):
        raise RuntimeError("secret interne")

    rig.service.receive = broken  # type: ignore[method-assign]
    safe = type(client)(app, raise_server_exceptions=False)
    response = post(safe, measurement(0), **{"X-Correlation-ID": "corr-500"})
    assert response.status_code == 500
    assert "secret interne" not in response.text
    problem = response.json()
    check(problem, PROBLEM)
    assert problem["code"] == "INTERNAL_ERROR"
    assert problem["correlation_id"] == "corr-500"
    assert response.headers["X-Correlation-ID"] == "corr-500"


# --- Autres routes ----------------------------------------------------------------------------


def test_the_route_only_accepts_post_and_says_so(client):
    response = client.get(URL)
    assert response.status_code == 405
    check(response.json(), PROBLEM)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "POST" in response.headers["allow"]


def test_an_unknown_route_answers_a_problem_not_the_framework_text(client):
    response = client.get("/api/v1/inconnue")
    assert response.status_code == 404
    check(response.json(), PROBLEM)
    assert response.json()["code"] == "NOT_FOUND"


def test_the_health_probe_still_works_without_kafka_or_mongodb():
    app.dependency_overrides.clear()
    from fastapi.testclient import TestClient

    assert TestClient(app).get("/api/v1/health").status_code == 200


def test_the_service_in_the_dependency_is_the_one_the_app_builds_by_default():
    assert app.dependency_overrides == {}
    assert get_ingestion_service.__name__ == "get_ingestion_service"


def test_the_response_body_is_json_utf8(client):
    response = post(client, measurement(0))
    assert json.loads(response.content)["status"] == "ACCEPTED"
    assert response.headers["content-type"].startswith("application/json")
