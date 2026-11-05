"""Câblage : composants de l'API, point d'entrée du travailleur, droits des rôles (MS-11)."""

import secrets
from types import SimpleNamespace

import pytest

from app.adapters.channels import LogChannel, WebhookChannel
from app.adapters.kafka_io import EventsReader
from app.adapters.postgres_store import PostgresAlertStore
from app.api import deps
from app.core.auth import LEVEL, Role, has_at_least
from app.core.config import Settings
from app.services.ports import StoreFailed
from app.worker import __main__ as worker_main


@pytest.fixture(autouse=True)
def no_leftover_components():
    deps.close_components()
    yield
    deps.close_components()


# ------------------------------------------------------------------------------------ composants
def test_without_configuration_the_store_is_absent_and_says_so():
    components = deps.build_components(Settings())
    assert isinstance(components.store, deps.NotConfiguredStore)
    assert components.reader is None  # pas de bus : pas de flux
    with pytest.raises(StoreFailed):
        components.store.rules()
    with pytest.raises(StoreFailed):
        components.store.transaction()


def test_with_a_database_and_a_bus_the_real_components_are_built_but_not_connected():
    settings = Settings(
        postgres_url="postgresql+psycopg://svc:pw-test-1234@postgres:5432/novaria",
        kafka_bootstrap_servers="kafka:9092",
    )
    components = deps.build_components(settings)
    assert isinstance(components.store, PostgresAlertStore)
    assert isinstance(components.reader, EventsReader)
    components.close()  # rien n'a été ouvert : fermer ne doit pas échouer


def test_the_stream_can_be_switched_off():
    settings = Settings(kafka_bootstrap_servers="kafka:9092", sse_enabled=False)
    assert deps.build_components(settings).reader is None


def test_components_start_the_reader_and_close_everything(monkeypatch):
    events = []

    class Reader:
        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

    components = deps.build_components(Settings())
    components.reader = Reader()
    components.closers.append(lambda: events.append("close"))
    components.start()
    components.close()
    assert events == ["start", "stop", "close"]


def test_components_are_created_once_per_process_and_can_be_reset(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    first = deps.get_components()
    assert deps.get_components() is first
    assert deps.get_store() is first.store and deps.get_service() is first.service
    assert deps.get_hub() is first.hub
    deps.close_components()
    assert deps.get_components() is not first
    deps.close_components()
    deps.close_components()  # sans composants : sans effet


# ------------------------------------------------------------------------------------------ rôles
@pytest.mark.parametrize(
    ("role", "minimum", "allowed"),
    [
        (Role.VIEWER, Role.VIEWER, True),
        (Role.VIEWER, Role.OPERATOR, False),
        (Role.OPERATOR, Role.VIEWER, True),
        (Role.OPERATOR, Role.OPERATOR, True),
        (Role.OPERATOR, Role.ADMIN, False),
        (Role.ADMIN, Role.VIEWER, True),
        (Role.ADMIN, Role.ADMIN, True),
    ],
)
def test_a_role_has_the_rights_of_the_roles_below_it(role, minimum, allowed):
    assert has_at_least(role, minimum) is allowed


def test_the_roles_are_the_three_of_the_contract_in_order():
    assert [r.value for r in sorted(LEVEL, key=LEVEL.get)] == ["viewer", "operator", "admin"]


# ------------------------------------------------------------------------------------- travailleur
def test_the_log_channel_is_the_default():
    assert isinstance(worker_main.build_channel(Settings()), LogChannel)


def test_the_webhook_channel_needs_its_address():
    with pytest.raises(ValueError, match="WEBHOOK_URL"):
        worker_main.build_channel(Settings(notification_channel="webhook"))
    channel = worker_main.build_channel(
        Settings(notification_channel="webhook", webhook_url="https://hooks.example/x")
    )
    assert isinstance(channel, WebhookChannel)


def test_the_worker_refuses_to_start_without_a_database_or_a_bus(monkeypatch, capsys):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    assert worker_main.main() == 1
    assert "obligatoires" in capsys.readouterr().out


class Closable:
    def __init__(self, *args, **kwargs):
        self.args, self.closed = args, False

    def close(self):
        self.closed = True


def wire_worker(monkeypatch, *, run_result=7, fail=False):
    """Remplace les adaptateurs par des faux : on vérifie l'assemblage et l'arrêt propre."""
    made = {}

    def keep(name):
        def build(*args, **kwargs):
            made[name] = Closable(*args, **kwargs)
            return made[name]

        return build

    def fake_run(*args, **kwargs):
        made["run"] = (args, kwargs)
        if fail:
            raise RuntimeError(secrets.token_urlsafe(12))
        return run_result

    monkeypatch.setenv(
        "POSTGRES_URL", "postgresql+psycopg://svc:pw-test-1234@postgres:5432/novaria"
    )
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.setenv("HEARTBEAT_FILE", "/srv/run/alive")
    monkeypatch.setattr(worker_main, "PostgresAlertStore", keep("store"))
    monkeypatch.setattr(worker_main, "KafkaPublisher", keep("publisher"))
    monkeypatch.setattr(worker_main, "KafkaSource", keep("source"))
    monkeypatch.setattr(worker_main, "AlertService", lambda store: "service")
    monkeypatch.setattr(worker_main, "RulesCache", lambda store, ttl: SimpleNamespace(get=list))
    monkeypatch.setattr(worker_main, "IndicatorHandler", lambda *a, **k: "handler")
    monkeypatch.setattr(worker_main, "Notifier", lambda *a, **k: "notifier")
    monkeypatch.setattr(worker_main, "OutboxRelay", lambda *a, **k: "relay")
    monkeypatch.setattr(worker_main, "run", fake_run)
    monkeypatch.setattr(worker_main.signal, "signal", lambda *a: None)
    return made


def test_the_worker_assembles_runs_and_closes_everything(monkeypatch):
    made = wire_worker(monkeypatch)
    assert worker_main.main() == 0
    args, kwargs = made["run"]
    assert args[:4] == ("handler", made["source"], "relay", "notifier")
    assert kwargs["heartbeat_file"] == "/srv/run/alive" and kwargs["poll_timeout_ms"] == 200
    assert made["source"].args[1:] == ("traffic.indicators", "alerte")
    assert made["store"].closed and made["publisher"].closed and made["source"].closed


def test_a_failure_stops_the_worker_with_a_code_and_still_closes(monkeypatch, capsys):
    made = wire_worker(monkeypatch, fail=True)
    assert worker_main.main() == 1
    out = capsys.readouterr().out
    assert "arrêt sur panne" in out and "RuntimeError" in out
    assert made["store"].closed and made["publisher"].closed and made["source"].closed
