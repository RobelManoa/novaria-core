"""Erreurs imprévues, erreurs du cadre et masquage des secrets dans les journaux (MS-08).

Les secrets d'essai sont générés à l'exécution : aucun secret, même factice, n'est écrit ici.
"""

import asyncio
import json
import logging
import secrets
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as HttpError

from app.core.config import get_settings
from app.core.errors import ProblemError, http_error_handler
from app.core.logs import configure_logging
from app.core.redaction import MASK, install_redaction, redact, secret_values
from app.core.unhandled import UnhandledErrorMiddleware
from app.main import app

# --- Erreurs ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "VALIDATION_ERROR"), (413, "VALIDATION_ERROR"), (502, "INTERNAL_ERROR")],
)
def test_other_http_errors_of_the_framework_keep_their_status_and_lose_their_text(status, code):
    response = asyncio.run(
        http_error_handler(None, HttpError(status, detail="texte anglais du cadre"))
    )
    body = json.loads(response.body)
    assert response.status_code == status
    assert body["code"] == code
    assert "anglais" not in body["detail"]


def test_a_problem_error_can_carry_headers_and_a_list_of_faulty_fields():
    error = ProblemError(
        app_kind(), "détail", errors=[{"field": "body.x", "message": "m"}], headers={"X-Test": "1"}
    )
    response = error.response()
    assert response.headers["x-test"] == "1"
    assert json.loads(response.body)["errors"] == [{"field": "body.x", "message": "m"}]


def app_kind():
    from app.core.errors import VALIDATION_ERROR

    return VALIDATION_ERROR


def test_an_error_after_the_response_started_is_not_hidden():
    async def half(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("après l'en-tête")

    async def run():
        async def receive():
            return {"type": "http.request"}

        async def send(_):
            return None

        await UnhandledErrorMiddleware(half)({"type": "http"}, receive, send)

    with pytest.raises(RuntimeError, match="après l'en-tête"):
        asyncio.run(run())


def test_a_non_http_scope_goes_through_untouched():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(UnhandledErrorMiddleware(inner)({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


def test_an_unexpected_error_is_logged_with_its_type_and_stack_but_not_its_message(caplog):
    leaked = secrets.token_urlsafe(24)

    async def crash(scope, receive, send):
        raise ValueError(leaked)

    async def run():
        async def receive():
            return {"type": "http.request"}

        async def send(_):
            return None

        await UnhandledErrorMiddleware(crash)({"type": "http"}, receive, send)

    asyncio.run(run())
    (record,) = [r for r in caplog.records if r.name == "app.errors"]
    assert record.fields["error"] == "ValueError"
    assert leaked not in caplog.text
    assert leaked not in record.fields["trace"]


def test_the_application_is_unchanged_by_a_get_on_the_health_probe():
    assert TestClient(app).get("/api/v1/health").json()["status"] == "ok"


# --- Masquage des secrets ---------------------------------------------------------------------


@pytest.fixture
def secrets_in_environment(monkeypatch):
    values = {"mongo": secrets.token_urlsafe(24), "other": secrets.token_urlsafe(24)}
    monkeypatch.setenv(
        "MONGO_URL",
        f"mongodb://svc_collecte:{values['mongo']}@mongo:27017/novaria?authSource=novaria",
    )
    monkeypatch.setenv("SERVICE_PASSWORD", values["other"])
    get_settings.cache_clear()
    yield values
    get_settings.cache_clear()


@pytest.fixture
def written(secrets_in_environment, capsys):
    configure_logging("collecte", "DEBUG")
    install_redaction()

    def write(message: str, **fields) -> str:
        capsys.readouterr()
        logging.getLogger("app.test").warning(message, extra={"fields": fields})
        return capsys.readouterr().out

    return write


def test_the_mongodb_address_and_its_password_come_out_masked_wherever_they_are(
    written, secrets_in_environment
):
    url = f"mongodb://svc_collecte:{secrets_in_environment['mongo']}@mongo:27017/novaria?authSource=novaria"
    out = written("échec " + url, url=url, nested={"dsn": [url]})
    assert secrets_in_environment["mongo"] not in out
    assert quote(secrets_in_environment["mongo"], safe="") not in out
    assert json.loads(out)["nested"] == {"dsn": [MASK]}


def test_a_secret_named_variable_is_masked_even_outside_a_url(written, secrets_in_environment):
    out = written(f"le mot de passe est {secrets_in_environment['other']}")
    assert secrets_in_environment["other"] not in out
    assert json.loads(out)["message"] == f"le mot de passe est {MASK}"


def test_a_secret_in_an_exception_message_is_masked(secrets_in_environment, capsys):
    configure_logging("collecte", "DEBUG")
    install_redaction()
    capsys.readouterr()
    try:
        raise RuntimeError(f"échec avec {secrets_in_environment['other']}")
    except RuntimeError:
        logging.getLogger("app.test").exception("panne")
    out = capsys.readouterr().out
    assert secrets_in_environment["other"] not in out
    assert "RuntimeError" in out


def test_an_opaque_bearer_token_and_a_jwt_shaped_value_are_masked_without_being_known():
    token = secrets.token_urlsafe(24)
    jwt_like = (
        "eyJ"
        + secrets.token_urlsafe(20)
        + "."
        + secrets.token_urlsafe(30)
        + "."
        + secrets.token_urlsafe(20)
    )
    text = redact(f"Bearer {token} puis {jwt_like}", [])
    assert token not in text
    assert jwt_like not in text


def test_url_credentials_are_masked_but_not_the_host():
    password = secrets.token_urlsafe(12)
    assert (
        redact(f"mongodb://compte:{password}@hote:27017/base", [])
        == "mongodb://compte:***@hote:27017/base"
    )


def test_short_values_are_not_searched_and_a_malformed_address_does_not_break_collection():
    assert secret_values({"SERVICE_PASSWORD": "court"}) == []
    password = secrets.token_urlsafe(12)
    assert secret_values({"BROKEN_URL": "http://[::1/x", "SERVICE_PASSWORD": password}) == [
        password
    ]


def test_an_invalid_configuration_does_not_break_the_logging(monkeypatch, capsys):
    monkeypatch.setenv("MAX_BODY_BYTES", "1")
    get_settings.cache_clear()
    configure_logging("collecte", "DEBUG")
    install_redaction()
    capsys.readouterr()
    logging.getLogger("app.test").warning("toujours écrit")
    assert "toujours écrit" in capsys.readouterr().out


def test_installing_twice_does_not_stack_formatters():
    from app.core.redaction import RedactingFormatter

    configure_logging("collecte", "INFO")
    install_redaction()
    install_redaction()
    for handler in logging.getLogger().handlers:
        assert isinstance(handler.formatter, RedactingFormatter)
        assert not isinstance(handler.formatter.inner, RedactingFormatter)
