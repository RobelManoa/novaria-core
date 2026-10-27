import json
import logging
import uuid

from fastapi.testclient import TestClient

from app.core.logs import CORRELATION_HEADER, JsonFormatter, correlation_id_var
from app.main import app

client = TestClient(app)


def journal_lines(capsys) -> list[dict]:
    """Lignes JSON écrites sur la sortie standard depuis le dernier appel."""
    return [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]


def test_a_correlation_id_is_generated_and_returned_when_missing():
    response = client.get("/api/v1/health")
    assert uuid.UUID(response.headers[CORRELATION_HEADER])


def test_a_sober_incoming_id_is_kept_returned_and_logged(capsys):
    response = client.get("/api/v1/health", headers={CORRELATION_HEADER: "req-123.A_b"})
    assert response.headers[CORRELATION_HEADER] == "req-123.A_b"
    entry = [line for line in journal_lines(capsys) if line["logger"] == "app.access"][-1]
    assert entry["correlation_id"] == "req-123.A_b"
    assert (entry["method"], entry["path"], entry["status"]) == ("GET", "/api/v1/health", 200)
    assert entry["duration_ms"] >= 0


def test_an_unsafe_incoming_id_is_replaced():
    response = client.get("/api/v1/health", headers={CORRELATION_HEADER: "a b; drop table"})
    assert uuid.UUID(response.headers[CORRELATION_HEADER])


def test_an_overlong_incoming_id_is_replaced():
    response = client.get("/api/v1/health", headers={CORRELATION_HEADER: "x" * 65})
    assert uuid.UUID(response.headers[CORRELATION_HEADER])


def test_the_query_string_is_never_logged_by_the_service(capsys):
    client.get("/api/v1/health?token=secret-value")
    own_lines = [line for line in journal_lines(capsys) if line["logger"].startswith("app.")]
    assert own_lines
    assert "secret-value" not in json.dumps(own_lines)


def test_uvicorn_does_not_log_requests_a_second_time():
    assert logging.getLogger("uvicorn.access").propagate is False
    assert logging.getLogger("uvicorn.error").propagate is True


def test_non_http_scopes_pass_through_the_middleware():
    with TestClient(app) as started:  # ouvre et ferme la portée « lifespan »
        assert started.get("/api/v1/health").status_code == 200


def test_every_line_has_the_documented_fields(capsys):
    client.get("/api/v1/health")
    for line in journal_lines(capsys):
        assert {"ts", "level", "service", "logger", "message", "correlation_id"} <= set(line)
        assert line["ts"].endswith("Z")


def record(**kwargs) -> logging.LogRecord:
    return logging.LogRecord(
        "essai", logging.WARNING, __file__, 1, "bonjour", None, kwargs.get("exc_info")
    )


def test_the_correlation_id_is_a_dash_outside_a_request():
    assert correlation_id_var.get() == "-"
    assert json.loads(JsonFormatter("essai").format(record()))["correlation_id"] == "-"


def test_extra_fields_cannot_overwrite_reserved_keys():
    rec = record()
    rec.fields = {"status": 200, "service": "pirate", "level": "FAKE"}
    entry = json.loads(JsonFormatter("essai").format(rec))
    assert entry["status"] == 200
    assert entry["service"] == "essai"
    assert entry["level"] == "WARNING"


def test_an_exception_is_logged_with_its_traceback():
    try:
        raise ValueError("boum")
    except ValueError:
        import sys

        entry = json.loads(JsonFormatter("essai").format(record(exc_info=sys.exc_info())))
    assert "ValueError: boum" in entry["exception"]
