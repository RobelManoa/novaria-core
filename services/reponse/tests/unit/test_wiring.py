"""Configuration, assemblage des composants et masquage des secrets du service de réponse (MS-12).

Les secrets d'essai sont générés à l'exécution : aucun secret, même factice, n'est écrit ici.
"""

import json
import logging
import secrets

import pytest
from pydantic import ValidationError

from app.api import deps
from app.core.auth import Role, has_at_least
from app.core.config import Settings, get_settings
from app.core.logs import configure_logging
from app.core.redaction import MASK, install_redaction
from app.services.ports import AuditFailed


# --------------------------------------------------------------------------- configuration
def settings(**env) -> Settings:
    return Settings(_env_file=None, **env)


def test_defaults_describe_the_demonstration_network_with_a_thirty_second_fixed_plan():
    s = settings()
    assert s.intersections == ["INT_01", "INT_02", "INT_03", "INT_04", "INT_05", "INT_06"]
    assert (s.fixed_phase_s, s.max_silence_s, s.command_rate_per_min) == (30, 180, 10)
    assert s.mongo_url is None and s.jwt_secret is None and s.kafka_bootstrap_servers == ""


def test_empty_secrets_from_compose_mean_not_configured():
    s = settings(mongo_url="", jwt_secret="")
    assert s.mongo_url is None and s.jwt_secret is None


def test_a_short_signing_key_is_refused_without_echoing_it():
    short = secrets.token_urlsafe(8)
    with pytest.raises(ValidationError) as error:
        settings(jwt_secret=short)
    assert short not in str(error.value)


@pytest.mark.parametrize("value", ["", ",,", "INT_1", "int_01", "INT_01;INT_02", "ROAD_001"])
def test_a_malformed_list_of_intersections_is_refused(value):
    with pytest.raises(ValidationError):
        settings(signal_intersections=value)


def test_intersections_are_deduplicated_in_order():
    assert settings(signal_intersections="INT_02, INT_01,INT_02").intersections == [
        "INT_02",
        "INT_01",
    ]


def test_the_example_secret_is_only_tolerated_locally():
    example = "change-me-local-" + secrets.token_urlsafe(30)
    assert settings(environment="local", jwt_secret=example).jwt_secret is not None
    with pytest.raises(ValidationError):
        settings(environment="production", jwt_secret=example)
    with pytest.raises(ValidationError):
        settings(environment="production", mongo_url=f"mongodb://svc:{example}@mongo/novaria")


@pytest.mark.parametrize(
    "bad",
    [
        {"fixed_phase_s": 0},
        {"max_silence_s": 1},
        {"command_rate_per_min": 0},
        {"tick_interval_s": 0},
    ],
)
def test_out_of_range_settings_are_refused(bad):
    with pytest.raises(ValidationError):
        settings(**bad)


# --------------------------------------------------------------------------- masquage
@pytest.fixture
def values(monkeypatch):
    found = {"password": secrets.token_urlsafe(24), "key": secrets.token_urlsafe(40)}
    monkeypatch.setenv(
        "MONGO_URL",
        f"mongodb://svc_reponse:{found['password']}@mongo:27017/novaria?authSource=novaria",
    )
    monkeypatch.setenv("JWT_SECRET", found["key"])
    get_settings.cache_clear()
    return found


@pytest.fixture
def written(values, capsys):
    configure_logging("reponse", "DEBUG")
    install_redaction()

    def write(message: str, **fields) -> str:
        capsys.readouterr()
        logging.getLogger("app.test").warning(message, extra={"fields": fields})
        return capsys.readouterr().out

    return write


def test_the_signing_key_never_reaches_the_logs(written, values):
    out = written(f"jeton {values['key']} refusé", token=values["key"])
    assert values["key"] not in out and MASK in out


def test_a_mongo_address_comes_out_masked_in_the_message_and_in_nested_fields(written, values):
    url = f"mongodb://svc_reponse:{values['password']}@mongo:27017/novaria"
    out = written("échec " + url, url=url, nested={"urls": [url]})
    assert values["password"] not in out
    assert json.loads(out)["nested"] == {
        "urls": [f"mongodb://svc_reponse:{MASK}@mongo:27017/novaria"]
    }


# --------------------------------------------------------------------------- rôles
@pytest.mark.parametrize(
    ("role", "minimum", "allowed"),
    [
        (Role.VIEWER, Role.VIEWER, True),
        (Role.VIEWER, Role.OPERATOR, False),
        (Role.OPERATOR, Role.OPERATOR, True),
        (Role.OPERATOR, Role.ADMIN, False),
        (Role.ADMIN, Role.OPERATOR, True),
    ],
)
def test_a_role_has_the_rights_of_the_roles_below_it(role, minimum, allowed):
    assert has_at_least(role, minimum) is allowed


# --------------------------------------------------------------------------- assemblage
@pytest.fixture(autouse=True)
def no_leftover_components():
    deps.close_components()
    yield
    deps.close_components()


def test_without_configuration_the_signals_run_at_the_fixed_plan_and_commands_are_refused(
    monkeypatch,
):
    for name in ("MONGO_URL", "KAFKA_BOOTSTRAP_SERVERS", "JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    components = deps.get_components()
    assert components.service.intersections[0] == "INT_01"
    assert components.runtime._handler is None  # rien à lire sans Kafka
    with pytest.raises(AuditFailed):
        components.audit.record({})
    with pytest.raises(AuditFailed):
        components.audit.history("INT_01", 5, None)


def test_with_mongo_and_kafka_the_real_adapters_are_built_without_connecting(monkeypatch):
    monkeypatch.setenv(
        "MONGO_URL", f"mongodb://svc:{secrets.token_urlsafe(12)}@127.0.0.1:1/novaria"
    )
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:1")
    get_settings.cache_clear()
    components = deps.get_components()
    assert (
        components.runtime._handler is not None and components.runtime._source_factory is not None
    )
    assert len(components.closers) == 2


def test_components_are_created_once_and_can_be_reset(monkeypatch):
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    first = deps.get_components()
    assert deps.get_components() is first
    deps.close_components()
    assert deps.get_components() is not first


def test_no_publisher_discards_everything():
    publisher = deps.NoPublisher()
    assert publisher.publish("t", None, b"x") is None and publisher.flush() is None
