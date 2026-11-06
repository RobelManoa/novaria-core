"""API d'alerte : authentification, lecture, actions, règles, conformité au contrat (MS-11)."""

import secrets
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.deps import NotConfiguredStore, get_hub, get_service, get_store
from app.domain.model import Kind
from app.main import app
from app.sse import EventHub
from tests.openapi_checks import PROBLEM, check, operations, schema
from tests.support import congested, indicator, silent

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
    hub = EventHub()
    app.dependency_overrides[get_store] = lambda: rig.store
    app.dependency_overrides[get_service] = lambda: rig.service
    app.dependency_overrides[get_hub] = lambda: hub
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def alert_id(rig, **kw) -> str:
    rig.feed(congested(0, **kw))
    return next(
        a.alert_id for a in rig.store.alerts() if a.road_segment_id == kw.get("segment", "ROAD_001")
    )


# --------------------------------------------------------------------------- authentification
def test_no_token_is_401_with_a_problem_body(client):
    reply = client.get("/api/v1/alerts")
    assert reply.status_code == 401
    assert reply.headers["content-type"].startswith("application/problem+json")
    assert reply.headers["www-authenticate"] == "Bearer"
    assert reply.json()["code"] == "UNAUTHENTICATED"
    check(reply.json(), PROBLEM)


@pytest.mark.parametrize(
    "bearer",
    [
        "pas-un-jeton",
        token(secret=secrets.token_urlsafe(48)),  # mauvaise signature
        token(exp=int(time.time()) - 10),  # expiré
        token(role="superuser"),  # rôle inconnu
        jwt.encode(
            {"sub": "u", "role": "viewer", "iat": 1, "exp": 4102444800}, key=None, algorithm="none"
        ),
    ],
)
def test_an_invalid_token_is_401_without_detail(client, bearer):
    reply = client.get("/api/v1/alerts", headers={"Authorization": f"Bearer {bearer}"})
    assert reply.status_code == 401 and reply.json()["code"] == "UNAUTHENTICATED"
    assert bearer not in reply.text


def test_a_token_without_required_claims_is_401(client):
    now = int(time.time())
    incomplete = jwt.encode(
        {"role": "viewer", "iat": now, "exp": now + 60}, SECRET, algorithm="HS256"
    )
    assert (
        client.get("/api/v1/alerts", headers={"Authorization": f"Bearer {incomplete}"}).status_code
        == 401
    )


def test_a_role_too_low_is_403(client, rig):
    identifier = alert_id(rig)
    reply = client.post(f"/api/v1/alerts/{identifier}/acknowledge", headers=auth("viewer"))
    assert reply.status_code == 403 and reply.json()["code"] == "FORBIDDEN"
    assert "operator" in reply.json()["detail"]
    check(reply.json(), PROBLEM)
    assert client.patch("/api/v1/alert-rules/capteur.muet", json={"enabled": False},
                        headers=auth("operator")).status_code == 403  # fmt: skip


def test_without_a_configured_secret_the_service_says_so(rig, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("JWT_SECRET", "")
    app.dependency_overrides[get_store] = lambda: rig.store
    try:
        from app.core.config import Settings, get_settings

        app.dependency_overrides[get_settings] = lambda: Settings(jwt_secret=None)
        reply = TestClient(app).get("/api/v1/alerts", headers=auth())
    finally:
        app.dependency_overrides.clear()
    assert reply.status_code == 503 and reply.json()["code"] == "UPSTREAM_UNAVAILABLE"


def test_the_health_probe_needs_no_token(client):
    assert client.get("/api/v1/health").status_code == 200


# ---------------------------------------------------------------------------------- lecture
def test_list_alerts_matches_the_contract_and_sorts_newest_first(client, rig):
    for minute, segment in ((0, "ROAD_001"), (5, "ROAD_002"), (9, "ROAD_003")):
        rig.feed(congested(minute, segment=segment))
    reply = client.get("/api/v1/alerts", headers=auth())
    assert reply.status_code == 200
    check(reply.json(), schema("AlertPage"))
    assert [a["road_segment_id"] for a in reply.json()["items"]] == [
        "ROAD_003",
        "ROAD_002",
        "ROAD_001",
    ]
    assert reply.json()["next_cursor"] is None


def test_pagination_follows_the_cursor_without_gaps_or_repeats(client, rig):
    for index in range(1, 6):
        rig.feed(congested(index, segment=f"ROAD_{index:03d}"))
    seen, cursor, pages = [], None, 0
    while True:
        query = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get("/api/v1/alerts", params=query, headers=auth()).json()
        seen += [a["alert_id"] for a in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and len(seen) == 5 == len(set(seen))


def test_the_last_page_has_no_cursor_even_when_the_total_is_a_multiple_of_the_page(client, rig):
    for index in range(1, 5):
        rig.feed(congested(index, segment=f"ROAD_{index:03d}"))
    first = client.get("/api/v1/alerts", params={"limit": 2}, headers=auth()).json()
    assert first["next_cursor"] is not None
    last = client.get(
        "/api/v1/alerts", params={"limit": 2, "cursor": first["next_cursor"]}, headers=auth()
    ).json()
    assert len(last["items"]) == 2 and last["next_cursor"] is None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"state": "CREATED"}, 3),
        ({"state": "RESOLVED"}, 0),
        ({"kind": "CONGESTION"}, 2),
        ({"kind": "SENSOR_FAULT"}, 1),
        ({"severity": "WARNING"}, 3),
        ({"severity": "CRITICAL"}, 0),
        ({"intersection_id": "INT_01"}, 3),
        ({"intersection_id": "INT_02"}, 0),
        ({"road_segment_id": "ROAD_002"}, 1),
        ({"opened_from": "2026-10-20T08:02:00Z"}, 2),  # ouvertes à 08:01, 08:02 et 08:03
        ({"opened_to": "2026-10-20T08:02:00Z"}, 2),
        ({"opened_from": "2026-10-20T08:02:00Z", "opened_to": "2026-10-20T08:02:00Z"}, 1),
    ],
)
def test_filters(client, rig, query, expected):
    rig.feed(congested(0), congested(2, segment="ROAD_002"), silent(1, segment="ROAD_003"))
    reply = client.get("/api/v1/alerts", params=query, headers=auth())
    assert reply.status_code == 200 and len(reply.json()["items"]) == expected


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ({"limit": 0}, "query.limit"),
        ({"limit": 501}, "query.limit"),
        ({"state": "BIZARRE"}, "query.state"),
        ({"kind": "X"}, "query.kind"),
        ({"intersection_id": "carrefour"}, "query.intersection_id"),
        ({"road_segment_id": "ROAD_1"}, "query.road_segment_id"),
        ({"opened_from": "hier"}, "query.opened_from"),
        ({"cursor": "n'importe quoi"}, "query.cursor"),
    ],
)
def test_invalid_queries_name_the_field(client, query, field):
    reply = client.get("/api/v1/alerts", params=query, headers=auth())
    assert reply.status_code == 422 and reply.json()["code"] == "VALIDATION_ERROR"
    assert [e["field"] for e in reply.json()["errors"]] == [field]
    check(reply.json(), PROBLEM)


def test_a_forged_cursor_with_valid_base64_is_refused(client):
    import base64

    forged = base64.urlsafe_b64encode(b'["pas une date", "pas un uuid"]').decode()
    assert (
        client.get("/api/v1/alerts", params={"cursor": forged}, headers=auth()).status_code == 422
    )
    not_a_list = base64.urlsafe_b64encode(b'{"a": 1}').decode()
    assert (
        client.get("/api/v1/alerts", params={"cursor": not_a_list}, headers=auth()).status_code
        == 422
    )


def test_get_alert_returns_its_history(client, rig):
    identifier = alert_id(rig)
    rig.notifier.run_once()
    reply = client.get(f"/api/v1/alerts/{identifier}", headers=auth())
    assert reply.status_code == 200
    body = reply.json()
    check(body, schema("AlertDetail"))
    assert [h["to_state"] for h in body["history"]] == ["CREATED", "NOTIFIED"]
    assert body["history"][0]["from_state"] is None and body["cause"] == "UNKNOWN"
    assert body["provenance"]["source_type"] == "SIMULATED"


@pytest.mark.parametrize(
    "identifier", ["00000000-0000-4000-8000-0000000000ff", "pas-un-uuid", "42"]
)
def test_an_unknown_alert_is_404(client, identifier):
    reply = client.get(f"/api/v1/alerts/{identifier}", headers=auth())
    assert reply.status_code == 404 and reply.json()["code"] == "NOT_FOUND"
    check(reply.json(), PROBLEM)


def test_unknown_routes_and_methods_are_problems(client):
    assert client.get("/api/v1/inconnu", headers=auth()).json()["code"] == "NOT_FOUND"
    assert client.delete("/api/v1/alerts", headers=auth()).json()["code"] == "METHOD_NOT_ALLOWED"


# ---------------------------------------------------------------------------------- actions
def test_acknowledge_writes_the_caller_and_is_idempotent(client, rig):
    identifier = alert_id(rig)
    first = client.post(
        f"/api/v1/alerts/{identifier}/acknowledge", headers=auth("operator", sub="user-42")
    )
    assert first.status_code == 200
    check(first.json(), schema("Alert"))
    assert (first.json()["state"], first.json()["acknowledged_by"]) == ("ACKNOWLEDGED", "user-42")
    events_before = len(rig.store.data.outbox)
    second = client.post(
        f"/api/v1/alerts/{identifier}/acknowledge", headers=auth("admin", sub="user-43")
    )
    assert second.status_code == 200 and second.json()["acknowledged_by"] == "user-42"
    assert len(rig.store.data.outbox) == events_before


def test_acknowledging_or_resolving_a_resolved_alert_is_409(client, rig):
    rig.feed(congested(0), indicator(1, "FREE_FLOW"))
    identifier = rig.store.alerts(Kind.CONGESTION)[0].alert_id
    for action in ("acknowledge", "resolve"):
        reply = client.post(f"/api/v1/alerts/{identifier}/{action}", headers=auth("operator"))
        assert reply.status_code == 409 and reply.json()["code"] == "INVALID_STATE_TRANSITION"
        check(reply.json(), PROBLEM)


def test_resolve_by_hand_with_a_comment(client, rig):
    identifier = alert_id(rig)
    reply = client.post(
        f"/api/v1/alerts/{identifier}/resolve",
        json={"comment": "agents sur place"},
        headers=auth("operator", sub="user-9"),
    )
    assert reply.status_code == 200
    check(reply.json(), schema("Alert"))
    assert (reply.json()["state"], reply.json()["resolution"]) == ("RESOLVED", "MANUAL")
    detail = client.get(f"/api/v1/alerts/{identifier}", headers=auth()).json()
    assert detail["history"][-1]["comment"] == "agents sur place"
    assert detail["history"][-1]["actor"] == "user-9"


def test_resolve_without_a_body_is_accepted(client, rig):
    identifier = alert_id(rig)
    assert (
        client.post(f"/api/v1/alerts/{identifier}/resolve", headers=auth("operator")).status_code
        == 200
    )


@pytest.mark.parametrize("body", [{"comment": "x" * 501}, {"autre": 1}, {"comment": 5}])
def test_resolve_refuses_a_bad_body(client, rig, body):
    identifier = alert_id(rig)
    reply = client.post(f"/api/v1/alerts/{identifier}/resolve", json=body, headers=auth("operator"))
    assert reply.status_code == 422 and reply.json()["errors"]
    check(reply.json(), PROBLEM)


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
def test_actions_on_an_unknown_alert_are_404(client, action):
    reply = client.post(
        f"/api/v1/alerts/00000000-0000-4000-8000-0000000000ff/{action}", headers=auth("operator")
    )
    assert reply.status_code == 404


# ----------------------------------------------------------------------------------- règles
def test_list_rules(client):
    reply = client.get("/api/v1/alert-rules", headers=auth())
    assert reply.status_code == 200
    items = reply.json()["items"]
    assert [r["rule_id"] for r in items] == [
        "congestion.persistante",
        "anomalie.circulation",
        "capteur.muet",
    ]
    for item in items:
        check(item, schema("AlertRule"))


def test_an_admin_can_disable_and_tune_a_rule(client, rig):
    changes = {"enabled": False, "min_gap_s": 120, "params": {"silence_s": 180}}
    reply = client.patch("/api/v1/alert-rules/capteur.muet", json=changes, headers=auth("admin"))
    assert reply.status_code == 200
    check(reply.json(), schema("AlertRule"))
    assert (reply.json()["enabled"], reply.json()["min_gap_s"], reply.json()["params"]) == (
        False,
        120,
        {"silence_s": 180},
    )
    rig.feed(silent(0))
    assert rig.store.alerts() == []  # la règle désactivée n'alerte plus


def test_rule_params_are_merged_not_replaced(client):
    reply = client.patch(
        "/api/v1/alert-rules/congestion.persistante",
        json={"params": {"min_windows": 2}},
        headers=auth("admin"),
    )
    assert reply.json()["params"] == {"state": "CONGESTED", "min_windows": 2}


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"params": {"min_windows": 0}}, ["body.params.min_windows"]),
        (
            {"params": {"inconnu": 1, "state": "FREE_FLOW"}},
            ["body.params.inconnu", "body.params.state"],
        ),
        ({"min_gap_s": -1}, ["body.min_gap_s"]),
        ({"enabled": "oui"}, ["body.enabled"]),
        ({"autre": 1}, ["body.autre"]),
        ({}, ["body"]),
    ],
)
def test_invalid_rule_changes_name_each_field(client, body, fields):
    reply = client.patch(
        "/api/v1/alert-rules/congestion.persistante", json=body, headers=auth("admin")
    )
    assert reply.status_code == 422
    assert sorted(e["field"] for e in reply.json()["errors"]) == sorted(fields)
    check(reply.json(), PROBLEM)


@pytest.mark.parametrize("rule_id", ["regle.inconnue", "X", "a b c"])
def test_an_unknown_rule_is_404(client, rule_id):
    reply = client.patch(
        f"/api/v1/alert-rules/{rule_id}", json={"enabled": False}, headers=auth("admin")
    )
    assert reply.status_code == 404


# -------------------------------------------------------------------------- base indisponible
def test_a_database_down_is_503_without_technical_detail(rig, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    app.dependency_overrides[get_store] = lambda: NotConfiguredStore()
    try:
        reply = TestClient(app).get("/api/v1/alerts", headers=auth())
    finally:
        app.dependency_overrides.clear()
    assert reply.status_code == 503 and reply.json()["code"] == "UPSTREAM_UNAVAILABLE"
    assert "POSTGRES_URL" not in reply.text
    check(reply.json(), PROBLEM)


def test_an_unexpected_error_is_a_500_problem_without_trace(client, rig, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("détail interne secret-ne-pas-montrer")

    monkeypatch.setattr(rig.store, "list_alerts", boom)
    reply = TestClient(app, raise_server_exceptions=False).get("/api/v1/alerts", headers=auth())
    assert reply.status_code == 500 and reply.json()["code"] == "INTERNAL_ERROR"
    assert "secret-ne-pas-montrer" not in reply.text


# ------------------------------------------------------------------------------------ contrat
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
