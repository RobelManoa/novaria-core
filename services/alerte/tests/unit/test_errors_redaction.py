"""Erreurs imprévues, erreurs du cadre, masquage des secrets et configuration (MS-11).

Les secrets d'essai sont générés à l'exécution : aucun secret, même factice, n'est écrit ici.
"""

import asyncio
import json
import logging
import secrets
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.exceptions import HTTPException as HttpError

from app.core.config import SECRET_SETTINGS, Settings, get_settings
from app.core.errors import VALIDATION_ERROR, ProblemError, http_error_handler
from app.core.logs import configure_logging
from app.core.redaction import MASK, RedactingFormatter, install_redaction, redact, secret_values
from app.core.unhandled import UnhandledErrorMiddleware
from app.main import app


# ---------------------------------------------------------------------------------------- erreurs
@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "VALIDATION_ERROR"), (413, "VALIDATION_ERROR"), (502, "INTERNAL_ERROR")],
)
def test_other_http_errors_of_the_framework_keep_their_status_and_lose_their_text(status, code):
    response = asyncio.run(
        http_error_handler(None, HttpError(status, detail="texte anglais du cadre"))
    )
    body = json.loads(response.body)
    assert response.status_code == status and body["code"] == code
    assert "anglais" not in body["detail"]


def test_a_problem_error_can_carry_headers_and_a_list_of_faulty_fields():
    error = ProblemError(
        VALIDATION_ERROR, "détail", errors=[{"field": "body.x", "message": "m"}],
        headers={"X-Test": "1"},
    )  # fmt: skip
    response = error.response()
    assert response.headers["x-test"] == "1"
    assert json.loads(response.body)["errors"] == [{"field": "body.x", "message": "m"}]


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
    assert leaked not in caplog.text and leaked not in record.fields["trace"]


def test_the_health_probe_answers_without_any_dependency():
    assert TestClient(app).get("/api/v1/health").json()["status"] == "ok"


# --------------------------------------------------------------------------- masquage des secrets
@pytest.fixture
def secrets_in_environment(monkeypatch):
    values = {
        "postgres": secrets.token_urlsafe(24),
        "jwt": secrets.token_urlsafe(40),
        "webhook": secrets.token_urlsafe(24),
    }
    monkeypatch.setenv(
        "POSTGRES_URL",
        f"postgresql+psycopg://svc_alerte:{values['postgres']}@postgres:5432/novaria",
    )
    monkeypatch.setenv("JWT_SECRET", values["jwt"])
    monkeypatch.setenv("WEBHOOK_URL", f"https://hooks.example/notify/{values['webhook']}")
    get_settings.cache_clear()
    yield values
    get_settings.cache_clear()


@pytest.fixture
def written(secrets_in_environment, capsys):
    configure_logging("alerte", "DEBUG")
    install_redaction()

    def write(message: str, **fields) -> str:
        capsys.readouterr()
        logging.getLogger("app.test").warning(message, extra={"fields": fields})
        return capsys.readouterr().out

    return write


def test_the_database_address_and_its_password_come_out_masked(written, secrets_in_environment):
    password = secrets_in_environment["postgres"]
    url = f"postgresql://svc_alerte:{password}@postgres:5432/novaria"
    out = written("échec " + url, url=url, nested={"dsn": [url]})
    assert password not in out and quote(password, safe="") not in out
    assert json.loads(out)["nested"] == {
        "dsn": [f"postgresql://svc_alerte:{MASK}@postgres:5432/novaria"]
    }


def test_the_signing_key_is_masked_even_outside_a_url(written, secrets_in_environment):
    out = written(f"clé {secrets_in_environment['jwt']}")
    assert secrets_in_environment["jwt"] not in out


def test_a_secret_in_an_exception_message_is_masked(secrets_in_environment, capsys):
    configure_logging("alerte", "DEBUG")
    install_redaction()
    capsys.readouterr()
    try:
        raise RuntimeError(f"échec avec {secrets_in_environment['jwt']}")
    except RuntimeError:
        logging.getLogger("app.test").exception("panne")
    out = capsys.readouterr().out
    assert secrets_in_environment["jwt"] not in out and "RuntimeError" in out


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
    assert token not in text and jwt_like not in text


def test_url_credentials_are_masked_but_not_the_host():
    password = secrets.token_urlsafe(12)
    assert (
        redact(f"postgresql://compte:{password}@hote:5432/base", [])
        == "postgresql://compte:***@hote:5432/base"
    )


def test_short_values_are_not_searched_and_a_malformed_address_does_not_break_collection():
    assert secret_values({"SERVICE_PASSWORD": "court"}) == []
    password = secrets.token_urlsafe(12)
    assert secret_values({"BROKEN_URL": "http://[::1/x", "SERVICE_PASSWORD": password}) == [
        password
    ]


def test_an_invalid_configuration_does_not_break_the_logging(monkeypatch, capsys):
    monkeypatch.setenv("SSE_QUEUE_SIZE", "0")
    get_settings.cache_clear()
    configure_logging("alerte", "DEBUG")
    install_redaction()
    capsys.readouterr()
    logging.getLogger("app.test").warning("toujours écrit")
    assert "toujours écrit" in capsys.readouterr().out


def test_installing_twice_does_not_stack_formatters():
    configure_logging("alerte", "INFO")
    install_redaction()
    install_redaction()
    for handler in logging.getLogger().handlers:
        assert isinstance(handler.formatter, RedactingFormatter)
        assert not isinstance(handler.formatter.inner, RedactingFormatter)


# ---------------------------------------------------------------------------------- configuration
def test_secret_settings_are_declared_and_hidden_in_a_representation():
    assert set(SECRET_SETTINGS) == {"postgres_url", "jwt_secret", "webhook_url"}
    password = secrets.token_urlsafe(16)
    settings = Settings(
        postgres_url=f"postgresql://u:{password}@h/db", jwt_secret=secrets.token_urlsafe(32)
    )
    assert password not in repr(settings) and password not in str(settings)


def test_a_refused_value_is_never_copied_into_the_error():
    leaked = secrets.token_urlsafe(24)
    with pytest.raises(ValidationError) as error:
        Settings(postgres_pool_max=leaked)
    assert leaked not in str(error.value)


def test_the_dsn_drops_the_sqlalchemy_driver_suffix_of_compose():
    settings = Settings(postgres_url="postgresql+psycopg://svc:pw-test-1234@postgres:5432/novaria")
    assert settings.dsn == "postgresql://svc:pw-test-1234@postgres:5432/novaria"
    assert Settings().dsn is None


def test_defaults_are_safe_without_any_configuration():
    settings = Settings()
    assert (settings.kafka_bootstrap_servers, settings.jwt_secret, settings.webhook_url) == (
        "",
        None,
        None,
    )
    assert settings.notification_channel == "log" and settings.sse_enabled


@pytest.mark.parametrize(
    "field",
    ["worker_poll_ms", "outbox_batch", "sse_queue_size", "sse_heartbeat_s", "postgres_pool_max",
     "notification_timeout_s", "kafka_publish_timeout_s"],
)  # fmt: skip
def test_numeric_settings_have_bounds(field):
    with pytest.raises(ValidationError):
        Settings(**{field: 0})
    with pytest.raises(ValidationError):
        Settings(**{field: 10**9})
