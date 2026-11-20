"""API publique de l'application citoyenne (CIT-03, ADR-030) : `GET /api/v1/public/congestion`.

Sans jeton, en lecture seule, six champs et aucun autre. L'état vient des indicateurs existants
(`dwh.v_indicator`), sans nouvelle source. Les tests vérifient surtout ce qui **ne sort pas** : les
comptages, les vitesses, les capteurs, la provenance interne.
"""

import json
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_indicator_repository
from app.main import app
from app.repositories.indicators import PublicSegmentRow
from app.schemas.public import PublicSegmentState
from tests.fakes import START, FakeIndicatorRepository, bearer, make_row
from tests.openapi_checks import TRAITEMENT, check, schema

PUBLIC = "/api/v1/public/congestion"
CHAMPS = {"road_segment_id", "intersection_id", "approach", "state", "updated_at", "simulated"}
# Ce que l'ADR-030 (section 4.4) interdit : aucun de ces noms dans une réponse publique.
INTERDITS = (
    "vehicle_count",
    "flow_veh_per_min",
    "average_speed_kmh",
    "speed_ratio",
    "sample_count",
    "expected_sample_count",
    "occupancy",
    "queue",
    "completeness",
    "classifier_version",
    "provenance",
    "run_id",
    "scenario_id",
    "seed",
    "dataset_id",
    "source_type",
    "sensor",
    "indicator_id",
    "window_start",
    "window_size_s",
)


@pytest.fixture
def repository():
    return FakeIndicatorRepository(approaches={"ROAD_001": "N", "ROAD_002": "E", "ROAD_003": "S"})


@pytest.fixture
def client(repository):
    app.dependency_overrides[get_indicator_repository] = lambda: repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def feed(repository, *rows):
    repository.rows.extend(rows)


def test_no_token_is_needed_and_the_body_matches_the_contract(client, repository):
    feed(repository, make_row())
    reply = client.get(PUBLIC)
    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("application/json")
    check(reply.json(), schema("PublicCongestionList", "traitement"))


def test_an_empty_warehouse_is_a_200_with_no_items_not_an_error(client):
    reply = client.get(PUBLIC)
    assert (reply.status_code, reply.json()) == (200, {"items": []})


def test_exactly_six_fields_and_nothing_internal_in_the_body(client, repository):
    feed(repository, make_row(), make_row(road_segment_id="ROAD_002", congestion_state="SLOW"))
    reply = client.get(PUBLIC)
    for item in reply.json()["items"]:
        assert set(item) == CHAMPS
    for forbidden in INTERDITS:
        assert forbidden not in reply.text, forbidden
    for value in ("run-demo-0001", "journee-calme", "regles-v0", "11.4", "140.0"):
        assert value not in reply.text, f"{value} est une valeur interne"


def test_the_state_comes_from_the_existing_indicators_with_the_side_of_the_segment(
    client, repository
):
    feed(
        repository,
        make_row(congestion_state="CONGESTED"),
        make_row(road_segment_id="ROAD_002", congestion_state="FREE_FLOW"),
        make_row(road_segment_id="ROAD_003", congestion_state="UNKNOWN"),
    )
    items = client.get(PUBLIC).json()["items"]
    assert [(i["road_segment_id"], i["approach"], i["state"]) for i in items] == [
        ("ROAD_001", "N", "CONGESTED"),
        ("ROAD_002", "E", "FREE_FLOW"),
        ("ROAD_003", "S", "UNKNOWN"),
    ]


def test_only_the_latest_window_of_the_latest_run_is_served(client, repository):
    feed(
        repository,
        make_row(congestion_state="CONGESTED", window_start=START),
        make_row(congestion_state="FREE_FLOW", window_start=START + timedelta(minutes=5)),
        make_row(
            road_segment_id="ROAD_002", run_id="ancien-run", window_start=START - timedelta(days=1)
        ),
        make_row(
            window_size_s=300, congestion_state="SLOW", window_start=START + timedelta(hours=1)
        ),
    )
    items = client.get(PUBLIC).json()["items"]
    assert [(i["road_segment_id"], i["state"]) for i in items] == [("ROAD_001", "FREE_FLOW")]


def test_updated_at_is_the_end_of_the_last_window_in_utc(client, repository):
    feed(repository, make_row(window_start=START))
    assert client.get(PUBLIC).json()["items"][0]["updated_at"] == "2026-10-20T08:21:00Z"


def test_simulated_is_true_for_the_simulator_and_false_otherwise(client, repository):
    feed(
        repository,
        make_row(road_segment_id="ROAD_001", source_type="SIMULATED"),
        make_row(road_segment_id="ROAD_002", source_type="REAL_HISTORICAL", dataset_id="metr-la"),
    )
    simulated = {i["road_segment_id"]: i["simulated"] for i in client.get(PUBLIC).json()["items"]}
    assert simulated == {"ROAD_001": True, "ROAD_002": False}


def test_a_token_is_ignored_and_gives_nothing_more(client, repository):
    feed(repository, make_row())
    anonymous = client.get(PUBLIC)
    for headers in (bearer_of("admin"), {"Authorization": "Bearer pas-un-jeton"}):
        reply = client.get(PUBLIC, headers=headers)
        assert (reply.status_code, reply.json()) == (anonymous.status_code, anonymous.json())


def bearer_of(role: str) -> dict:
    from app.models import Role, User

    return bearer(User(user_id=None, username="x", password_hash="x", role=Role(role)))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_write_is_refused(client, repository, method):
    feed(repository, make_row())
    before = list(repository.rows)
    assert client.request(method, PUBLIC, json={}).status_code == 405
    assert repository.rows == before


@pytest.mark.parametrize(
    "path",
    ["/api/v1/public", "/api/v1/public/", "/api/v1/public/congestion/x", "/api/v1/public/signals"],
)
def test_nothing_else_exists_under_the_public_space(client, path):
    assert client.get(path).status_code == 404


def test_the_mapper_copies_six_fields_and_nothing_else():
    row = PublicSegmentRow(
        road_segment_id="ROAD_001",
        intersection_id="INT_01",
        approach="W",
        congestion_state="SLOW",
        window_start=START,
        source_type="SIMULATED",
    )
    out = PublicSegmentState.from_row(row).model_dump()
    assert set(out) == CHAMPS
    assert out["state"] == "SLOW" and out["approach"] == "W"
    with pytest.raises(ValueError):
        PublicSegmentState(**out, vehicle_count=3)  # un champ de plus est refusé


def test_the_audit_counts_the_call_by_route_and_never_stores_who_called(client, repository):
    from tests.fakes import Journal

    journal = Journal()
    app.state.observer = journal.observer
    try:
        client.get(
            f"{PUBLIC}?jeton=valeur-secrete&nom=Dupont", headers={"Authorization": "Bearer x"}
        )
    finally:
        del app.state.observer
    assert journal.audit.entries == [], "un appel sans identité n'écrit aucune entrée d'audit"
    assert journal.usage.total(f"GET {PUBLIC}") == 1, "il est seulement compté, sous son modèle"
    assert "valeur-secrete" not in str([list(journal.usage.counts), journal.audit.entries])


def test_the_query_string_reaches_neither_the_journal_nor_the_metrics(client, repository, capsys):
    feed(repository, make_row())
    client.get(f"{PUBLIC}?jeton=valeur-secrete-xyz&nom=Dupont")
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    own = [
        line for line in lines if line["logger"].startswith("app.")
    ]  # le client de test journalise la sienne
    assert own
    assert "valeur-secrete-xyz" not in json.dumps(own) and "Dupont" not in json.dumps(own)
    text = client.get("/metrics").text
    assert "valeur-secrete-xyz" not in text and "Dupont" not in text
    assert re.search(r'route="[^"]*/public/congestion"', text), "l'étiquette est le modèle de route"


def test_the_contract_declares_the_route_public_and_read_only():
    item = TRAITEMENT["paths"][PUBLIC]
    assert set(item) == {"get"}
    assert item["get"]["security"] == []
