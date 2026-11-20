"""API publique de l'application citoyenne (CIT-03, ADR-030) : `GET /api/v1/public/alerts`.

Sans jeton, en lecture seule, six champs et aucun autre. Les tests vérifient surtout ce qui
**ne sort pas** : le nom de l'opérateur, la cause, la règle, l'épisode, la provenance interne,
les défauts de capteur et les alertes résolues.
"""

import json
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.deps import NotConfiguredStore, get_hub, get_service, get_store
from app.api.mapping import public_alert_out
from app.domain.model import Alert, Kind, Provenance, Severity, State
from app.main import app
from app.sse import EventHub
from tests.openapi_checks import PROBLEM, check, schema
from tests.support import congested, silent
from tests.unit.test_api import SECRET, auth

PUBLIC = "/api/v1/public/alerts"
CHAMPS = {"alert_id", "road_segment_id", "intersection_id", "severity", "opened_at", "simulated"}
# Ce que l'ADR-030 (section 4.4) interdit : aucun de ces noms dans une réponse publique.
INTERDITS = (
    "acknowledged_by",
    "acknowledged_at",
    "notified_at",
    "cause",
    "rule_id",
    "episode_id",
    "resolution",
    "resolved_at",
    "provenance",
    "run_id",
    "scenario_id",
    "seed",
    "state",
    "kind",
    "history",
    "sensor",
)


@pytest.fixture
def client(rig, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    app.dependency_overrides[get_store] = lambda: rig.store
    app.dependency_overrides[get_service] = lambda: rig.service
    app.dependency_overrides[get_hub] = lambda: EventHub()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def alerts_of(rig) -> list[Alert]:
    return list(rig.store.alerts())


def test_no_token_is_needed_and_the_body_matches_the_contract(client, rig):
    rig.feed(congested(0))
    reply = client.get(PUBLIC)
    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("application/json")
    check(reply.json(), schema("PublicAlertList"))
    assert len(reply.json()["items"]) == 1


def test_an_empty_list_is_a_200_not_an_error(client):
    reply = client.get(PUBLIC)
    assert (reply.status_code, reply.json()) == (200, {"items": []})


def test_exactly_six_fields_and_nothing_internal_in_the_body(client, rig):
    rig.feed(congested(0))
    item = client.get(PUBLIC).json()["items"][0]
    assert set(item) == CHAMPS
    assert item["simulated"] is True
    text = client.get(PUBLIC).text
    for forbidden in INTERDITS:
        assert forbidden not in text, forbidden
    assert "run-test" not in text, "l'identifiant du run est interne"


def test_the_name_of_the_operator_who_acknowledged_never_leaves(client, rig):
    rig.feed(congested(0))
    identifier = alerts_of(rig)[0].alert_id
    done = client.post(
        f"/api/v1/alerts/{identifier}/acknowledge", headers=auth("operator", sub="operateur-secret")
    )
    assert done.status_code == 200 and done.json()["acknowledged_by"] == "operateur-secret"
    reply = client.get(PUBLIC)
    assert "operateur-secret" not in reply.text
    assert set(reply.json()["items"][0]) == CHAMPS
    assert [a["alert_id"] for a in reply.json()["items"]] == [identifier], (
        "reconnue, elle reste en cours"
    )


def test_a_resolved_alert_is_no_longer_listed(client, rig):
    rig.feed(congested(0, segment="ROAD_001"), congested(1, segment="ROAD_002"))
    first = next(a for a in alerts_of(rig) if a.road_segment_id == "ROAD_001")
    assert (
        client.post(
            f"/api/v1/alerts/{first.alert_id}/resolve", json={}, headers=auth("operator")
        ).status_code
        == 200
    )
    assert [a["road_segment_id"] for a in client.get(PUBLIC).json()["items"]] == ["ROAD_002"]


def test_a_sensor_fault_is_not_a_public_alert(client, rig):
    rig.feed(silent(0, segment="ROAD_001"))
    assert any(a.kind == Kind.SENSOR_FAULT for a in alerts_of(rig)), "le défaut existe côté équipe"
    assert client.get(PUBLIC).json() == {"items": []}
    assert client.get("/api/v1/alerts", headers=auth()).json()["items"], (
        "et reste visible de l'équipe"
    )


def test_newest_first_and_the_list_is_bounded(client, rig):
    for index in range(1, 106):
        rig.feed(congested(index, segment=f"ROAD_{index:03d}"))
    items = client.get(PUBLIC).json()["items"]
    assert len(items) == 100
    assert items[0]["road_segment_id"] == "ROAD_105"
    assert [i["opened_at"] for i in items] == sorted((i["opened_at"] for i in items), reverse=True)


def test_a_token_is_ignored_and_gives_nothing_more(client, rig):
    rig.feed(congested(0))
    anonymous = client.get(PUBLIC)
    for headers in (auth("admin"), {"Authorization": "Bearer pas-un-jeton"}):
        reply = client.get(PUBLIC, headers=headers)
        assert (reply.status_code, reply.json()) == (anonymous.status_code, anonymous.json())


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_write_is_refused(client, rig, method):
    rig.feed(congested(0))
    reply = client.request(method, PUBLIC, json={}, headers=auth("admin"))
    assert reply.status_code == 405
    assert len(alerts_of(rig)) == 1 and alerts_of(rig)[0].state != State.RESOLVED


@pytest.mark.parametrize(
    "path",
    ["/api/v1/public", "/api/v1/public/", "/api/v1/public/alerts/x", "/api/v1/public/signals"],
)
def test_nothing_else_exists_under_the_public_space(client, path):
    assert client.get(path).status_code == 404


def test_a_store_that_is_down_is_a_503_without_detail(rig, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    rig.store.down = True
    app.dependency_overrides[get_store] = lambda: rig.store
    try:
        reply = TestClient(app).get(PUBLIC)
    finally:
        app.dependency_overrides.clear()
    assert reply.status_code == 503 and reply.json()["code"] == "UPSTREAM_UNAVAILABLE"
    check(reply.json(), PROBLEM)
    assert "base indisponible" not in reply.text


def test_without_a_database_the_route_says_so(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    app.dependency_overrides[get_store] = lambda: NotConfiguredStore()
    try:
        reply = TestClient(app).get(PUBLIC)
    finally:
        app.dependency_overrides.clear()
    assert reply.status_code == 503 and "POSTGRES_URL" not in reply.text


def test_the_query_string_reaches_neither_the_journal_nor_the_metrics(client, rig, capsys):
    rig.feed(congested(0))
    client.get(f"{PUBLIC}?jeton=valeur-secrete-xyz&nom=Dupont")
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    own = [
        line for line in lines if line["logger"].startswith("app.")
    ]  # le client de test journalise la sienne
    assert own
    assert "valeur-secrete-xyz" not in json.dumps(own) and "Dupont" not in json.dumps(own)
    access = [line for line in own if line["logger"] == "app.access"]
    assert access and access[-1]["path"] == PUBLIC
    text = client.get("/metrics").text
    assert "valeur-secrete-xyz" not in text and "Dupont" not in text
    assert re.search(r'route="[^"]*/public/alerts"', text), "l'étiquette est le modèle de route"


def test_the_public_mapper_copies_six_fields_and_says_whether_the_data_is_simulated():
    moment = datetime(2026, 11, 20, 8, 18, 30, tzinfo=UTC)

    def alert(source_type: str) -> Alert:
        return Alert(
            alert_id="3f0c1f0e-8a52-4d3c-9d58-1b9a3e5c7a10",
            rule_id="congestion.persistante",
            kind=Kind.CONGESTION,
            road_segment_id="ROAD_002",
            intersection_id="INT_01",
            provenance=Provenance(
                source_type=source_type, run_id="run-interne", scenario_id="s", seed=1
            ),
            severity=Severity.WARNING,
            state=State.ACKNOWLEDGED,
            opened_at=moment,
            acknowledged_by="operateur",
            episode_id="e",
            correlation_id="c",
        )

    simulated, real = (
        public_alert_out(alert("SIMULATED")),
        public_alert_out(alert("REAL_HISTORICAL")),
    )
    assert set(simulated) == CHAMPS == set(real)
    assert (simulated["simulated"], real["simulated"]) == (True, False)
    assert simulated["opened_at"] == "2026-11-20T08:18:30Z"
    assert "operateur" not in json.dumps(simulated) and "run-interne" not in json.dumps(simulated)


def test_the_contract_example_is_what_the_service_would_answer(client, rig):
    rig.feed(congested(0))
    item = client.get(PUBLIC).json()["items"][0]
    check({"items": [item]}, schema("PublicAlertList"))
    assert item["severity"] in ("INFO", "WARNING", "CRITICAL")
