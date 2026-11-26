"""Les routes des réseaux de vitesse respectent le contrat OpenAPI du traitement (IA-16, ADR-032).

Chaque réponse est valide contre les schémas `SpeedNetwork` et `SpeedForecastList` ; les bornes des
paramètres sont celles du contrat ; sans
modèle utilisable la réponse est 503 `FORECAST_UNAVAILABLE`, jamais une persistance présentée comme
un modèle.
"""

import pytest

from app.api.v1.speed_networks import get_speed_service
from app.main import app
from app.models import Role
from app.services.speed_forecasts import SpeedForecastService
from tests.fakes import bearer
from tests.openapi_checks import PROBLEM, TRAITEMENT, check, schema
from tests.speed_data import T0, FakeSpeedRepository, model_bytes

NETWORKS = "/api/v1/speed-networks"
FORECASTS = NETWORKS + "/metr-la/forecasts"
CONTRACT = TRAITEMENT["paths"]["/api/v1/speed-networks/{network_id}/forecasts"]["get"]


@pytest.fixture
def viewer(repo):
    return bearer(repo.make("lecteur", Role.VIEWER))


@pytest.fixture
def models(tmp_path):
    (tmp_path / "prevision-metr-la-reseau.json").write_bytes(model_bytes())
    return tmp_path


@pytest.fixture
def with_model(client, models):
    app.dependency_overrides[get_speed_service] = lambda: SpeedForecastService(
        FakeSpeedRepository(), models
    )


@pytest.fixture
def without_model(client, tmp_path):
    app.dependency_overrides[get_speed_service] = lambda: SpeedForecastService(
        FakeSpeedRepository(), tmp_path
    )


def get(client, viewer, url, **params):
    return client.get(url, headers=viewer, params=params)


def test_the_service_declares_the_operations_of_the_contract():
    paths = app.openapi()["paths"]
    for chemin, operation_id in (
        (NETWORKS, "listSpeedNetworks"),
        ("/api/v1/speed-networks/{network_id}/forecasts", "listSpeedForecasts"),
    ):
        declared = paths[chemin]["get"]
        wanted = TRAITEMENT["paths"][chemin]["get"]
        assert wanted["operationId"] == operation_id
        assert declared["x-required-role"] == wanted["x-required-role"] == "viewer"
        assert set(declared["responses"]) == set(wanted["responses"])


def test_the_parameters_have_the_bounds_of_the_contract():
    declared = {
        p["name"]: p
        for p in app.openapi()["paths"]["/api/v1/speed-networks/{network_id}/forecasts"]["get"][
            "parameters"
        ]
    }
    wanted = {p["name"]: p for p in CONTRACT["parameters"]}
    assert set(declared) == set(wanted) == {"network_id", "as_of", "horizon_min", "sensor_id"}
    horizon = declared["horizon_min"]["schema"]
    assert (horizon["minimum"], horizon["maximum"], horizon["default"]) == (5, 30, 15)
    assert wanted["horizon_min"]["schema"]["maximum"] == 30


def test_the_listing_is_valid_and_carries_the_model_card(client, viewer, with_model):
    reponse = get(client, viewer, NETWORKS)
    assert reponse.status_code == 200
    [network] = reponse.json()["items"]
    check(network, schema("SpeedNetwork", "traitement"))
    assert network["model"]["kind"] == "MODEL" and network["model_problem"] is None
    assert network["model"]["test"]["15"]["gain"] == 0.17
    assert network["coverage"]["sensors"] == 4


def test_the_listing_without_a_model_says_why(client, viewer, without_model):
    [network] = get(client, viewer, NETWORKS).json()["items"]
    check(network, schema("SpeedNetwork", "traitement"))
    assert network["model"] is None and "Aucun modèle" in network["model_problem"]


def test_a_forecast_is_valid_against_the_contract(client, viewer, with_model):
    reponse = get(client, viewer, FORECASTS, as_of="2012-06-20T08:00:00Z", horizon_min=15)
    assert reponse.status_code == 200
    corps = reponse.json()
    check(corps, schema("SpeedForecastList", "traitement"))
    assert corps["as_of"] == "2012-06-20T08:00:00Z" and corps["model"]["kind"] == "MODEL"
    assert [i["sensor_id"] for i in corps["items"]][0] == "773869"
    assert corps["items"][0]["observed_speed_kmh"] is not None


def test_an_as_of_without_a_zone_is_read_as_utc(client, viewer, with_model):
    assert (
        get(client, viewer, FORECASTS, as_of="2012-06-20T08:00:00").json()["as_of"]
        == "2012-06-20T08:00:00Z"
    )


def test_the_sensor_filter_and_its_bound(client, viewer, with_model):
    corps = get(client, viewer, FORECASTS, sensor_id=["767541"]).json()
    assert [i["sensor_id"] for i in corps["items"]] == ["767541"]
    assert get(client, viewer, FORECASTS, sensor_id=[str(i) for i in range(51)]).status_code == 422


@pytest.mark.parametrize("horizon", [0, 4, 31, 7, 12])
def test_a_horizon_out_of_the_contract_is_a_422(client, viewer, with_model, horizon):
    reponse = get(client, viewer, FORECASTS, horizon_min=horizon)
    assert reponse.status_code == 422
    check(reponse.json(), PROBLEM)


def test_without_a_model_the_answer_is_a_503_never_a_persistence(client, viewer, without_model):
    reponse = get(client, viewer, FORECASTS)
    assert reponse.status_code == 503
    check(reponse.json(), PROBLEM)
    assert reponse.json()["code"] == "FORECAST_UNAVAILABLE"
    assert "Aucun modèle" in reponse.json()["detail"]


def test_unknown_network_and_date_before_the_data_are_404s(client, viewer, with_model):
    inconnu = get(client, viewer, NETWORKS + "/nulle-part/forecasts")
    assert inconnu.status_code == 404 and inconnu.json()["code"] == "NOT_FOUND"
    avant = get(client, viewer, FORECASTS, as_of="2000-01-01T00:00:00Z")
    assert avant.status_code == 404
    check(avant.json(), PROBLEM)


def test_a_malformed_network_id_is_a_422(client, viewer, with_model):
    assert get(client, viewer, NETWORKS + "/Pas Valide/forecasts").status_code == 422


def test_authentication_is_required(client, with_model):
    for url in (NETWORKS, FORECASTS):
        reponse = client.get(url)
        assert reponse.status_code == 401
        check(reponse.json(), PROBLEM)


def test_the_instant_of_the_last_measures_is_what_the_answer_is_based_on(
    client, viewer, with_model
):
    assert (
        get(client, viewer, FORECASTS).json()["as_of"] == "2012-06-20T09:00:00Z"
    )  # T0 + 1 h : la fin du réseau d'essai
    assert T0.isoformat().startswith("2012-06-20T08:00")
