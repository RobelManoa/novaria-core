"""Middleware d'audit (BE-05) : branchement ASGI, pannes et absence de configuration."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.core.audit import AuditMiddleware
from app.core.config import get_settings
from app.db import observer as observer_module
from app.main import app
from app.models import Role
from app.services.audit import RequestEvent
from tests.fakes import bearer


class Recording:
    def __init__(self) -> None:
        self.events: list[RequestEvent] = []

    def observe(self, event: RequestEvent) -> None:
        self.events.append(event)


class Exploding:
    def observe(self, event: RequestEvent) -> None:
        raise RuntimeError("ne doit pas casser la réponse")


async def answer(scope, receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def crash(scope, receive, send):
    raise RuntimeError("route cassée")


def scope_for(path="/api/v1/users", method="GET", state=None, observer=None) -> dict:
    app.state.observer = observer
    return {
        "type": "http",
        "method": method,
        "path": path,
        "app": app,
        "state": state or {},
        "path_params": {},
    }


async def run(middleware, scope):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


@pytest.fixture(autouse=True)
def clean_observer():
    yield
    app.state.observer = None


def test_the_event_carries_the_status_the_route_and_the_caller_of_the_call():
    recording = Recording()
    state = {"actor": "u-1", "role": "admin"}
    asyncio.run(run(AuditMiddleware(answer), scope_for(state=state, observer=recording)))
    (event,) = recording.events
    assert (event.method, event.template, event.status) == ("GET", "/api/v1/users", 204)
    assert (event.actor, event.role) == ("u-1", "admin")
    assert event.started_at.tzinfo is UTC
    assert event.started_at <= datetime.now(UTC)
    assert event.duration_ms >= 0


def test_an_unhandled_error_is_recorded_as_a_500_and_still_propagates():
    recording = Recording()
    with pytest.raises(RuntimeError, match="route cassée"):
        asyncio.run(run(AuditMiddleware(crash), scope_for(observer=recording)))
    assert [e.status for e in recording.events] == [500]


def test_an_error_after_the_response_started_keeps_the_status_that_was_sent():
    recording = Recording()

    async def late_failure(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("flux interrompu")

    with pytest.raises(RuntimeError):
        asyncio.run(run(AuditMiddleware(late_failure), scope_for(observer=recording)))
    assert [e.status for e in recording.events] == [200]


def test_the_probe_produces_no_event():
    recording = Recording()
    asyncio.run(run(AuditMiddleware(answer), scope_for(path="/api/v1/health", observer=recording)))
    assert recording.events == []


def test_other_scopes_than_http_pass_through_untouched():
    recording = Recording()
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    scope = scope_for(observer=recording) | {"type": "websocket"}
    asyncio.run(run(AuditMiddleware(inner), scope))
    assert seen == ["websocket"]
    assert recording.events == []


def test_without_an_observer_the_call_goes_through(monkeypatch):
    monkeypatch.setattr("app.core.audit.get_observer", lambda: None)
    sent = asyncio.run(run(AuditMiddleware(answer), scope_for(observer=None)))
    assert sent[0]["status"] == 204


def test_the_templates_are_compiled_once_and_kept_on_the_application():
    app.state.audit_templates = None
    recording = Recording()
    asyncio.run(run(AuditMiddleware(answer), scope_for(observer=recording)))
    first = app.state.audit_templates
    asyncio.run(run(AuditMiddleware(answer), scope_for(observer=recording)))
    assert first and app.state.audit_templates is first


def test_the_observer_of_the_configuration_is_used_when_none_is_set_on_the_app(monkeypatch):
    recording = Recording()
    monkeypatch.setattr("app.core.audit.get_observer", lambda: recording)
    asyncio.run(run(AuditMiddleware(answer), scope_for(observer=None)))
    assert len(recording.events) == 1


def test_a_broken_journal_does_not_change_the_response(client, repo, journal):
    class Broken:
        def insert(self, entry):
            raise ConnectionError("injoignable")

    journal.observer._audit = Broken()
    appelant = repo.make("appelant", Role.ADMIN)
    reponse = client.get("/api/v1/auth/me", headers=bearer(appelant))
    assert reponse.status_code == 200
    assert journal.observer.dropped == 1
    assert journal.usage.counts == {}
    assert journal.failures[0][1]["error"] == "ConnectionError"


# --- Construction de l'observateur ----------------------------------------------------------


@pytest.fixture
def fresh_settings(monkeypatch):
    monkeypatch.delenv("AUDIT_MONGO_URL", raising=False)
    get_settings.cache_clear()
    observer_module.get_observer.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()
    observer_module.get_observer.cache_clear()


def test_without_an_audit_address_nothing_is_written_and_a_warning_is_logged(
    fresh_settings, caplog
):
    with caplog.at_level("WARNING", logger="app.audit"):
        assert observer_module.get_observer() is None
    assert "AUDIT_MONGO_URL" in caplog.text


def test_with_an_audit_address_the_observer_is_built_once_and_the_address_is_not_logged(
    fresh_settings, caplog
):
    opened = []

    class Depot:
        def __init__(self, nom):
            self.nom = nom

    def fake_open(url):
        opened.append(url)
        return Depot("audit"), Depot("usage")

    fresh_settings.setenv("AUDIT_MONGO_URL", "mongodb://svc_backend:SECRET-PW@mongo:27017/novaria")
    fresh_settings.setattr(observer_module, "open_collections", fake_open)
    get_settings.cache_clear()
    with caplog.at_level("DEBUG"):
        first = observer_module.get_observer()
        assert observer_module.get_observer() is first
    assert opened == ["mongodb://svc_backend:SECRET-PW@mongo:27017/novaria"]
    assert "SECRET-PW" not in caplog.text


def test_a_write_failure_is_logged_as_a_structured_error_without_the_address(caplog):
    with caplog.at_level("ERROR", logger="app.audit"):
        observer_module.log_failure("écriture impossible", {"error": "ConnectionError"})
    (record,) = caplog.records
    assert record.fields == {"error": "ConnectionError"}
    assert record.levelname == "ERROR"


def test_the_settings_do_not_show_the_audit_address():
    from pydantic import SecretStr

    from app.core.config import Settings

    reglages = Settings(audit_mongo_url=SecretStr("mongodb://u:SECRET-PW@h/db"))
    assert "SECRET-PW" not in repr(reglages)
    assert "SECRET-PW" not in str(reglages.model_dump())
