"""API de réponse : authentification, lecture, commande manuelle, conformité au contrat (MS-12)."""

import secrets
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_audit, get_service
from app.domain.model import Mode
from app.main import app
from tests.openapi_checks import PROBLEM, check, operations, schema
from tests.support import raw, recommendation_event

SECRET = secrets.token_urlsafe(48)  # généré à l'exécution : aucune valeur secrète dans le dépôt


def token(role: str = "viewer", *, secret: str = SECRET, sub: str = "user-1", **claims) -> str:
    now = int(time.time())
    payload = {"sub": sub, "role": role, "iat": now, "exp": now + 600, **claims}
    return jwt.encode(payload, secret, algorithm="HS256")


def auth(role: str = "viewer", **kwargs) -> dict:
    return {"Authorization": f"Bearer {token(role, **kwargs)}"}


@pytest.fixture
def client(rig, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    app.dependency_overrides[get_service] = lambda: rig.service
    app.dependency_overrides[get_audit] = lambda: rig.audit
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def command(client, body, role="operator", intersection="INT_01", **kwargs):
    return client.post(
        f"/api/v1/signals/{intersection}/commands", json=body, headers=auth(role, **kwargs)
    )


SET_P2 = {"action": "SET_PHASE", "phase_id": "P2", "duration_s": 30, "reason": "Évacuation"}


# =========================================================================== authentification
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/signals"),
        ("GET", "/api/v1/signals/INT_01"),
        ("GET", "/api/v1/signals/INT_01/commands"),
        ("POST", "/api/v1/signals/INT_01/commands"),
    ],
)
def test_every_route_but_health_needs_a_token(client, method, path):
    response = client.request(method, path, json=SET_P2)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "UNAUTHENTICATED"
    check(response.json(), PROBLEM)


def test_health_needs_no_token(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"


@pytest.mark.parametrize(
    "bad",
    [
        {"Authorization": "Bearer pas-un-jeton"},
        {"Authorization": f"Bearer {token(secret=secrets.token_urlsafe(48))}"},
        {"Authorization": f"Bearer {token(exp=int(time.time()) - 10)}"},
    ],
)
def test_a_forged_or_expired_token_is_refused(client, bad):
    assert client.get("/api/v1/signals", headers=bad).status_code == 401


def test_a_viewer_reads_but_cannot_command(client):
    assert client.get("/api/v1/signals", headers=auth("viewer")).status_code == 200
    denied = command(client, SET_P2, role="viewer")
    assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN"
    check(denied.json(), PROBLEM)


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_operators_and_admins_can_command(client, rig, role):
    rig.advance(12)
    assert command(client, SET_P2, role=role).status_code == 202


def test_without_a_configured_secret_the_service_answers_503_not_200(rig, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    app.dependency_overrides[get_service] = lambda: rig.service
    try:
        response = TestClient(app).get("/api/v1/signals", headers=auth())
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503 and response.json()["code"] == "UPSTREAM_UNAVAILABLE"


# =========================================================================== lecture
def test_the_state_of_every_equipped_intersection_follows_the_contract(client):
    response = client.get("/api/v1/signals", headers=auth())
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["intersection_id"] for i in items] == ["INT_01", "INT_02"]
    for item in items:
        check(item, schema("SignalState"))
        assert item["mode"] == "DEGRADED_FIXED_PLAN" and item["decision"]["origin"] == "STARTUP"


def test_the_state_changes_with_the_clock_without_any_event(client, rig):
    first = client.get("/api/v1/signals/INT_01", headers=auth()).json()
    assert (first["current_phase_id"], first["signal"], first["green_approaches"]) == (
        "P1",
        "GREEN",
        ["N", "S"],
    )
    rig.clock.advance(27)
    cleared = client.get("/api/v1/signals/INT_01", headers=auth()).json()
    assert (cleared["signal"], cleared["green_approaches"]) == ("ALL_RED", [])
    rig.clock.advance(5)
    second = client.get("/api/v1/signals/INT_01", headers=auth()).json()
    assert (second["current_phase_id"], second["green_approaches"]) == ("P2", ["E", "W"])


def test_the_state_shows_the_recommendation_that_produced_it(client, rig):
    rig.handler.handle(raw(recommendation_event()))
    state = client.get("/api/v1/signals/INT_01", headers=auth()).json()
    assert state["mode"] == "AUTOMATIC" and state["decision"]["origin"] == "RECOMMENDATION"
    assert [p["duration_s"] for p in state["phases"]] == [40, 20]
    check(state, schema("SignalState"))


@pytest.mark.parametrize("intersection", ["INT_09", "BAD", "int_01", "INT_1"])
def test_an_unknown_or_malformed_intersection_is_404(client, intersection):
    for path in ("", "/commands"):
        response = client.get(f"/api/v1/signals/{intersection}{path}", headers=auth())
        assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"
    assert command(client, SET_P2, intersection=intersection).status_code == 404


# =========================================================================== commande manuelle
def test_a_safe_command_is_accepted_applied_and_visible_in_the_state(client, rig):
    rig.advance(12)
    response = command(client, SET_P2, sub="operator-7")
    assert response.status_code == 202
    body = response.json()
    check(body, schema("SignalCommand"))
    assert (body["status"], body["requested_by"], body["phase_id"]) == (
        "APPLIED",
        "operator-7",
        "P2",
    )
    assert body["intersection_id"] == "INT_01" and body["refusal_reason"] is None
    assert response.headers["location"] == "/api/v1/signals/INT_01"
    state = client.get("/api/v1/signals/INT_01", headers=auth()).json()
    assert state["mode"] == "MANUAL" and state["decision"]["reference_id"] == body["command_id"]
    [entry] = rig.audit.of("signal.command.")
    assert entry["actor"] == "operator-7" and entry["details"]["role"] == "operator"


@pytest.mark.parametrize(
    ("body", "advance", "reason", "field"),
    [
        ({**SET_P2, "duration_s": 9}, 12, "PHASE_TOO_SHORT", "body.duration_s"),
        ({**SET_P2, "duration_s": 91}, 12, "PHASE_TOO_LONG", "body.duration_s"),
        ({**SET_P2, "phase_id": "P7"}, 12, "UNKNOWN_PHASE", "body.phase_id"),
        (SET_P2, 5, "MIN_DURATION_NOT_ELAPSED", "body"),
        (SET_P2, 27, "CLEARANCE_IN_PROGRESS", "body"),
    ],
)
def test_a_dangerous_command_is_422_unsafe_and_leaves_the_signals_untouched(
    client, rig, body, advance, reason, field
):
    rig.advance(advance)
    before = client.get("/api/v1/signals/INT_01", headers=auth()).json()
    response = command(client, body)
    assert response.status_code == 422
    problem = response.json()
    assert problem["code"] == "UNSAFE_COMMAND" and problem["detail"].startswith(reason)
    assert problem["errors"] == [{"field": field, "message": reason}]
    check(problem, PROBLEM)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert client.get("/api/v1/signals/INT_01", headers=auth()).json() == before
    [entry] = rig.audit.of("signal.command.")
    assert entry["outcome"] == "denied" and entry["details"]["refusal_reason"] == reason


def test_a_second_command_while_one_runs_is_409(client, rig):
    rig.advance(12)
    command(client, SET_P2)
    second = command(client, {**SET_P2, "phase_id": "P1"})
    assert second.status_code == 409
    assert second.json()["code"] == "COMMAND_IN_PROGRESS"
    check(second.json(), PROBLEM)


@pytest.mark.parametrize(
    "body",
    [
        {"action": "SET_PHASE", "reason": "sans phase"},
        {"action": "SET_PHASE", "phase_id": "P2", "reason": "sans durée"},
        {**SET_P2, "duration_s": 0},
        {**SET_P2, "duration_s": 601},
        {**SET_P2, "phase_id": "deux"},
        {**SET_P2, "reason": "ab"},
        {**SET_P2, "reason": "x" * 501},
        {**SET_P2, "reason": "ligne1\nligne2"},
        {**SET_P2, "unknown": 1},
        {"action": "JUMP", "reason": "inconnue"},
        {"reason": "sans action"},
    ],
)
def test_an_invalid_body_is_a_validation_error_before_any_guardrail(client, rig, body):
    rig.advance(12)
    response = command(client, body)
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["errors"][0]["field"].startswith("body")
    check(response.json(), PROBLEM)
    assert rig.audit.entries == [] and rig.service.view("INT_01").mode is not Mode.MANUAL


def test_resuming_automatic_ignores_a_phase_it_does_not_need(client, rig):
    rig.advance(12)
    command(client, SET_P2)
    rig.advance(20)
    response = command(client, {"action": "RESUME_AUTOMATIC", "phase_id": "P1", "reason": "fin"})
    assert response.status_code == 202
    body = response.json()
    assert (body["action"], body["phase_id"], body["duration_s"]) == (
        "RESUME_AUTOMATIC",
        None,
        None,
    )
    assert client.get("/api/v1/signals/INT_01", headers=auth()).json()["mode"] != "MANUAL"


def test_a_command_is_refused_with_503_when_it_cannot_be_journaled(client, rig):
    rig.advance(12)
    rig.audit.down = True
    response = command(client, SET_P2)
    assert response.status_code == 503 and response.json()["code"] == "UPSTREAM_UNAVAILABLE"
    assert "appliquée" in response.json()["detail"]
    assert client.get("/api/v1/signals/INT_01", headers=auth()).json()["mode"] != "MANUAL"


def test_the_correlation_id_of_the_request_reaches_the_journal(client, rig):
    rig.advance(12)
    headers = {**auth("operator"), "X-Correlation-ID": "trace-abc-123"}
    response = client.post("/api/v1/signals/INT_01/commands", json=SET_P2, headers=headers)
    assert response.headers["x-correlation-id"] == "trace-abc-123"
    assert rig.audit.of("signal.command.")[0]["correlation_id"] == "trace-abc-123"


def test_the_reason_is_journaled_trimmed_but_never_logged_or_published(client, rig, caplog):
    rig.advance(12)
    command(client, {**SET_P2, "reason": "  Évacuation après incident  "})
    assert rig.audit.of("signal.command.")[0]["details"]["reason"] == "Évacuation après incident"
    rig.flush()
    assert "incident" not in str(rig.status()) and "incident" not in caplog.text


def test_too_many_commands_in_a_minute_is_429_with_retry_after(client, rig):
    for _ in range(10):
        command(client, {**SET_P2, "duration_s": 9}, sub="u-spam")
    response = command(client, SET_P2, sub="u-spam")
    assert response.status_code == 429 and response.json()["code"] == "RATE_LIMITED"
    assert 1 <= int(response.headers["retry-after"]) <= 60
    check(response.json(), PROBLEM)
    assert command(client, SET_P2, sub="u-other").status_code != 429


# =========================================================================== historique
def test_the_command_history_lists_applied_and_refused_commands_newest_first(client, rig):
    rig.advance(12)
    command(client, {**SET_P2, "duration_s": 9}, sub="u-a")
    command(client, SET_P2, sub="u-b")
    response = client.get("/api/v1/signals/INT_01/commands", headers=auth())
    assert response.status_code == 200
    body = response.json()
    check(body, schema("SignalCommandPage"))
    assert [(i["status"], i["requested_by"]) for i in body["items"]] == [
        ("APPLIED", "u-b"),
        ("REFUSED", "u-a"),
    ]
    assert body["items"][1]["refusal_reason"] == "PHASE_TOO_SHORT" and body["next_cursor"] is None


def test_the_command_history_is_paginated(client, rig):
    rig.advance(12)
    for _ in range(3):
        command(client, {**SET_P2, "duration_s": 9})
    first = client.get("/api/v1/signals/INT_01/commands?limit=2", headers=auth()).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    last = client.get(
        f"/api/v1/signals/INT_01/commands?limit=2&cursor={first['next_cursor']}", headers=auth()
    ).json()
    assert len(last["items"]) == 1 and last["next_cursor"] is None


def test_the_history_of_one_intersection_does_not_show_another(client, rig):
    rig.advance(12)
    command(client, SET_P2, intersection="INT_02")
    assert client.get("/api/v1/signals/INT_01/commands", headers=auth()).json()["items"] == []


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "limit=abc", "cursor=%25%25", "cursor=" + "x" * 201]
)
def test_a_bad_history_query_is_a_validation_error(client, query):
    response = client.get(f"/api/v1/signals/INT_01/commands?{query}", headers=auth())
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"


def test_the_history_is_503_when_the_journal_is_down(client, rig):
    rig.audit.down = True
    response = client.get("/api/v1/signals/INT_01/commands", headers=auth())
    assert response.status_code == 503 and response.json()["code"] == "UPSTREAM_UNAVAILABLE"


# =========================================================================== contrat
def test_every_operation_of_the_contract_exists_with_the_same_role_and_id(client):
    served = client.get("/openapi.json").json()["paths"]
    for (method, path), operation in operations().items():
        assert path in served and method.lower() in served[path], f"{method} {path} non servi"
        mine = served[path][method.lower()]
        assert mine["operationId"] == operation["operationId"]
        assert mine.get("x-required-role") == operation.get("x-required-role"), (method, path)


def test_every_route_served_is_in_the_contract(client):
    contract = set(operations())
    for path, item in client.get("/openapi.json").json()["paths"].items():
        for method in item:
            assert (method.upper(), path) in contract, f"{method.upper()} {path} absent du contrat"


def test_declared_error_codes_are_in_the_contract(client):
    served = client.get("/openapi.json").json()["paths"]
    for (method, path), operation in operations().items():
        wanted = {c for c in operation["responses"] if c.isdigit() and c.startswith("4")}
        mine = {c for c in served[path][method.lower()]["responses"] if c.startswith("4")}
        assert wanted <= mine | {"422"}, (method, path, wanted - mine)


def test_an_unexpected_error_is_a_500_problem_without_trace(client, rig, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("détail interne secret-ne-pas-montrer")

    monkeypatch.setattr(rig.service, "views", boom)
    reply = TestClient(app, raise_server_exceptions=False).get("/api/v1/signals", headers=auth())
    assert reply.status_code == 500 and reply.json()["code"] == "INTERNAL_ERROR"
    assert "secret-ne-pas-montrer" not in reply.text
