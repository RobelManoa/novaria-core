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


def test_correlation_of_reads_the_id_of_a_json_message():
    from app.core.logs import correlation_of

    assert correlation_of(b'{"correlation_id": "corr-1794923710000"}') == "corr-1794923710000"
    assert correlation_of('{"correlation_id": "abc.def_1"}') == "abc.def_1"


def test_correlation_of_refuses_what_is_not_a_sober_id():
    from app.core.logs import correlation_of

    for raw in (
        b"{}",
        b"pas du json",
        b"[]",
        None,
        b'{"correlation_id": 12}',
        b'{"correlation_id": "a b"}',
        b'{"correlation_id": "' + b"x" * 65 + b'"}',
    ):
        assert correlation_of(raw) == "-", raw


def test_bound_correlation_labels_the_lines_of_the_block_and_restores_the_previous_id(capsys):
    from app.core.logs import JsonFormatter, bound_correlation

    logger = logging.getLogger("essai.corr")
    record = logger.makeRecord("essai.corr", logging.INFO, __file__, 1, "ligne", (), None)
    token = correlation_id_var.set("requete-1")
    try:
        with bound_correlation("message-9"):
            inside = json.loads(JsonFormatter("essai").format(record))["correlation_id"]
        after = json.loads(JsonFormatter("essai").format(record))["correlation_id"]
        with bound_correlation("-"), bound_correlation(None):
            unchanged = json.loads(JsonFormatter("essai").format(record))["correlation_id"]
    finally:
        correlation_id_var.reset(token)
    assert (inside, after, unchanged) == ("message-9", "requete-1", "requete-1")
