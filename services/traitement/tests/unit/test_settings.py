"""Configuration lue dans l'environnement (BE-08) : secrets, valeurs d'exemple, bornes."""

import secrets

import pytest
from pydantic import ValidationError

from app.core.config import SECRET_SETTINGS, Settings

PLACEHOLDER_URL = "postgresql+psycopg://svc_app:change-me-local@postgres:5432/novaria"


def long_secret() -> str:
    return secrets.token_urlsafe(48)


# --- Un secret refusé n'est jamais recopié ----------------------------------------------------


def test_a_secret_that_is_too_short_is_refused_without_being_written_in_the_message():
    weak = secrets.token_urlsafe(8)
    with pytest.raises(ValidationError) as error:
        Settings(jwt_secret=weak)
    text = str(error.value)
    assert "JWT_SECRET doit avoir au moins 32 caractères" in text
    assert weak not in text  # ce que Python écrit quand le démarrage échoue


def test_a_refused_url_is_not_written_in_the_message_either():
    password = secrets.token_urlsafe(16)
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="dev", app_database_url=f"postgresql://u:change-me-local{password}@h/d"
        )
    assert password not in str(error.value)
    assert "APP_DATABASE_URL" in str(error.value)


def test_a_wrong_type_does_not_echo_the_value_of_a_secret_setting():
    with pytest.raises(ValidationError) as error:
        Settings(login_max_failures="beaucoup")
    assert "beaucoup" not in str(error.value)


def test_secrets_do_not_appear_when_the_settings_are_printed():
    jwt, url = long_secret(), f"mongodb://svc:{long_secret()}@mongo/novaria"
    settings = Settings(jwt_secret=jwt, audit_mongo_url=url)
    for rendering in (repr(settings), str(settings), settings.model_dump_json()):
        assert jwt not in rendering
        assert url not in rendering
        assert url.split(":")[2].split("@")[0] not in rendering


# --- La valeur d'exemple n'est pas un secret --------------------------------------------------


@pytest.mark.parametrize("name", SECRET_SETTINGS)
@pytest.mark.parametrize("environment", ["dev", "demo", "prod", "Local"])
def test_the_example_value_is_refused_outside_the_local_environment(name, environment):
    value = "change-me-local-at-least-32-characters" if name == "jwt_secret" else PLACEHOLDER_URL
    with pytest.raises(ValidationError) as error:
        Settings(environment=environment, **{name: value})
    assert name.upper() in str(error.value)
    assert "change-me" not in str(error.value)


@pytest.mark.parametrize("name", SECRET_SETTINGS)
def test_the_example_value_is_tolerated_locally_where_init_env_is_the_normal_path(name):
    value = "change-me-local-at-least-32-characters" if name == "jwt_secret" else PLACEHOLDER_URL
    assert getattr(Settings(environment="local", **{name: value}), name) is not None


def test_real_values_are_accepted_in_every_environment():
    for environment in ("local", "dev", "prod"):
        settings = Settings(
            environment=environment,
            jwt_secret=long_secret(),
            app_database_url=f"postgresql+psycopg://svc_app:{long_secret()}@postgres/novaria",
        )
        assert settings.jwt_secret is not None


def test_without_any_secret_the_service_starts_and_says_nothing_is_configured():
    settings = Settings(environment="prod")
    assert settings.jwt_secret is None
    assert settings.app_database_url is None


# --- Les secrets viennent de l'environnement ou de .env ---------------------------------------


def test_a_secret_is_read_from_the_environment(monkeypatch):
    value = long_secret()
    monkeypatch.setenv("JWT_SECRET", value)
    assert Settings().jwt_secret.get_secret_value() == value


def test_a_secret_is_read_from_the_env_file_the_environment_wins_over_it(tmp_path, monkeypatch):
    in_file, in_env = long_secret(), long_secret()
    (tmp_path / ".env").write_text(f"JWT_SECRET={in_file}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    assert Settings().jwt_secret.get_secret_value() == in_file
    monkeypatch.setenv("JWT_SECRET", in_env)
    assert Settings().jwt_secret.get_secret_value() == in_env


def test_no_secret_has_a_default_value_in_the_code():
    for name in SECRET_SETTINGS:
        assert Settings.model_fields[name].default is None, name


# --- Bornes -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("login_attempts_per_minute", 0),
        ("login_max_failures", 0),
        ("login_lockout_s", 5),
        ("trusted_proxy_hops", -1),
        ("trusted_proxy_hops", 6),
    ],
)
def test_the_limits_cannot_be_switched_off_or_set_absurdly(name, value):
    with pytest.raises(ValidationError):
        Settings(**{name: value})


def test_the_defaults_are_restrictive():
    settings = Settings()
    assert settings.cors_origins == []
    assert settings.trusted_proxy_hops == 0
    assert settings.login_attempts_per_minute == 10
    assert settings.login_max_failures == 5
    assert settings.login_lockout_s == 900
