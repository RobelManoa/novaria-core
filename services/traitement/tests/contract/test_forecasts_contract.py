"""La route de prévisions respecte le contrat OpenAPI du traitement (IA-06).

`GET /api/v1/forecasts` rend la référence par persistance tant qu'aucun modèle n'a battu la
référence (ADR-015) : chaque réponse est valide contre le schéma `Forecast` du contrat, les
paramètres ont les bornes du contrat, et la réponse ne prétend jamais être un modèle entraîné.
"""

from datetime import timedelta

import pytest

from app.main import app
from app.models import Role
from tests.fakes import START, bearer, make_row
from tests.openapi_checks import PROBLEM, TRAITEMENT, check, schema

FORECASTS = "/api/v1/forecasts"
FORECAST = schema("Forecast", "traitement")
CONTRACT = TRAITEMENT["paths"][FORECASTS]["get"]


@pytest.fixture
def viewer(repo):
    return bearer(repo.make("lecteur", Role.VIEWER))


@pytest.fixture
def seeded(indicators):
    indicators.rows += [
        make_row(road_segment_id="ROAD_001", speed_ratio=0.228, congestion_state="CONGESTED"),
        make_row(road_segment_id="ROAD_002", speed_ratio=0.95, congestion_state="FREE_FLOW"),
        make_row(road_segment_id="ROAD_003", speed_ratio=0.5, congestion_state="SLOW"),
    ]
    return indicators


def get(client, viewer, **params):
    return client.get(FORECASTS, headers=viewer, params=params)


def test_the_service_declares_the_operation_of_the_contract():
    operation = app.openapi()["paths"][FORECASTS]["get"]
    assert CONTRACT["operationId"] == "listForecasts"
    assert operation["x-required-role"] == CONTRACT["x-required-role"] == "viewer"
    assert set(operation["responses"]) == set(CONTRACT["responses"])


def test_the_parameters_have_the_bounds_of_the_contract():
    declared = {
        p["name"]: p["schema"] for p in app.openapi()["paths"][FORECASTS]["get"]["parameters"]
    }
    contract = {p["name"]: p["schema"] for p in CONTRACT["parameters"]}
    horizon, wanted = declared["horizon_min"], contract["horizon_min"]
    assert (horizon["minimum"], horizon["maximum"], horizon["default"]) == (
        wanted["minimum"],
        wanted["maximum"],
        wanted["default"],
    )
    segments = next(s for s in declared["road_segment_id"]["anyOf"] if s.get("type") == "array")
    assert segments["maxItems"] == contract["road_segment_id"]["maxItems"] == 50
    assert segments["items"]["pattern"] == r"^ROAD_[0-9]{3,}$"


def test_every_forecast_is_valid_against_the_contract_schema(client, viewer, seeded):
    response = get(client, viewer)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items"}
    assert [item["road_segment_id"] for item in body["items"]] == [
        "ROAD_001",
        "ROAD_002",
        "ROAD_003",
    ]
    for item in body["items"]:
        check(item, FORECAST)


def test_the_answer_says_it_is_a_reference_and_not_a_trained_model(client, viewer, seeded):
    for item in get(client, viewer).json()["items"]:
        assert item["model"] == {
            "kind": "REFERENCE",
            "name": "persistance",
            "version": "1",
            "run_id": None,
        }
        assert "trained_at" not in item["model"], "aucune date d'entraînement n'est inventée"
        assert "metrics" not in item["model"], "aucune métrique n'est inventée"


def test_the_value_and_the_state_are_those_of_the_last_known_minute(client, viewer, seeded):
    first = get(client, viewer, road_segment_id="ROAD_001").json()["items"][0]
    assert (first["predicted_speed_ratio"], first["predicted_state"]) == (0.228, "CONGESTED")
    assert first["provenance"] == {
        "source_type": "SIMULATED",
        "run_id": "run-demo-0001",
        "scenario_id": "journee-calme",
        "seed": 42,
    }


def test_issue_and_target_times_are_utc_and_follow_the_horizon(client, viewer, seeded):
    item = get(client, viewer, road_segment_id="ROAD_001", horizon_min=45).json()["items"][0]
    assert item["issued_at"] == (START + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert item["target_time"] == (START + timedelta(minutes=46)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert item["horizon_min"] == 45


def test_the_default_horizon_is_fifteen_minutes(client, viewer, seeded):
    assert get(client, viewer, road_segment_id="ROAD_001").json()["items"][0]["horizon_min"] == 15


def test_a_repeated_parameter_asks_for_several_segments(client, viewer, seeded):
    response = client.get(
        f"{FORECASTS}?road_segment_id=ROAD_003&road_segment_id=ROAD_001", headers=viewer
    )
    assert [i["road_segment_id"] for i in response.json()["items"]] == ["ROAD_001", "ROAD_003"]


def test_an_unknown_segment_gives_an_empty_list_not_an_error(client, viewer, seeded):
    response = get(client, viewer, road_segment_id="ROAD_999")
    assert (response.status_code, response.json()) == (200, {"items": []})


def test_without_any_data_the_answer_is_the_documented_503(client, viewer):
    response = get(client, viewer)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    check(body, PROBLEM)
    assert body["code"] == "FORECAST_UNAVAILABLE"
    assert "postgresql" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "horizon_min=4",
        "horizon_min=61",
        "horizon_min=quinze",
        "road_segment_id=ROAD_1",
        "road_segment_id=segment",
        "&".join(f"road_segment_id=ROAD_{n:03d}" for n in range(51)),
    ],
)
def test_a_parameter_outside_the_contract_is_a_422_that_names_the_field(
    client, viewer, seeded, query
):
    response = client.get(f"{FORECASTS}?{query}", headers=viewer)
    assert response.status_code == 422, response.text
    body = response.json()
    check(body, PROBLEM)
    assert body["code"] == "VALIDATION_ERROR"
    assert all(error["field"].startswith("query.") for error in body["errors"])


def test_fifty_segments_are_accepted(client, viewer, seeded):
    query = "&".join(f"road_segment_id=ROAD_{n:03d}" for n in range(50))
    assert client.get(f"{FORECASTS}?{query}", headers=viewer).status_code == 200


def test_the_route_needs_a_token(client, seeded):
    response = client.get(FORECASTS)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_a_call_is_audited_like_the_other_reads(client, viewer, seeded, journal):
    assert get(client, viewer).status_code == 200
    (entry,) = journal.entries
    assert entry["action"] == f"GET {FORECASTS}"
    assert (entry["outcome"], entry["details"]["status"]) == ("ok", 200)
