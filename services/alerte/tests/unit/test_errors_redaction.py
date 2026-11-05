"""Masquage des secrets dans les journaux et configuration du service d'alerte (MS-11).

Les secrets d'essai sont générés à l'exécution : aucun secret, même factice, n'est écrit ici.
"""

import json
import logging
import secrets
from urllib.parse import quote

import pytest
from pydantic import ValidationError

from app.core.config import SECRET_SETTINGS, Settings, get_settings
from app.core.logs import configure_logging
from app.core.redaction import MASK, install_redaction


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


# ----------------------------------------------------------------------- clé des jetons (BE-08)
def test_a_signing_key_that_is_too_short_is_refused_without_being_copied():
    short = secrets.token_urlsafe(8)
    with pytest.raises(ValidationError) as error:
        Settings(jwt_secret=short)
    assert "au moins 32" in str(error.value) and short not in str(error.value)
    Settings(jwt_secret=secrets.token_urlsafe(32))  # 43 caractères : accepté


@pytest.mark.parametrize("name", ["jwt_secret", "webhook_url", "postgres_url"])
def test_an_empty_value_from_compose_means_not_configured(name):
    assert getattr(Settings(**{name: ""}), name) is None


def test_the_example_value_is_tolerated_in_local_only():
    example = "change-me-local-at-least-32-characters"
    assert Settings(jwt_secret=example).jwt_secret is not None
    with pytest.raises(ValidationError) as error:
        Settings(environment="production", jwt_secret=example)
    assert "JWT_SECRET" in str(error.value) and example not in str(error.value)
    with pytest.raises(ValidationError):
        Settings(environment="production", webhook_url="https://hooks.example/change-me-local")
    assert Settings(environment="production", jwt_secret=secrets.token_urlsafe(48)).jwt_secret
