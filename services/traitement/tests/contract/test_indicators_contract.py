"""Les routes d'indicateurs respectent le contrat OpenAPI du traitement (BE-04).

Critère d'acceptation : les réponses respectent le contrat. Les tests partent de
`contracts/openapi/traitement.openapi.yaml` :
- les paramètres de la route sont ceux du contrat : mêmes bornes, motifs et valeurs admises ;
- chaque réponse (page, détail, dernier indicateur par tronçon, erreur) est validée contre le
  schéma du contrat ;
- les filtres de période et de zone, la pagination par curseur et les erreurs 401, 404 et 422
  se comportent comme le contrat les décrit.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.main import app
from app.models import Role
from tests.fakes import START, FakeIndicatorRepository, bearer, make_row
from tests.openapi_checks import OPENAPI, PROBLEM, TRAITEMENT, check, load, schema

LIST = "/api/v1/indicators"
LATEST = "/api/v1/indicators/latest"
OPERATIONS = {
    ("/api/v1/indicators", "get"): "listIndicators",
    ("/api/v1/indicators/latest", "get"): "listLatestIndicators",
    ("/api/v1/indicators/{indicator_id}", "get"): "getIndicator",
}
PAGE = schema("IndicatorPage", "traitement")
INDICATOR = schema("Indicator", "traitement")


def contract_operation(path: str, method: str = "get") -> dict:
    return TRAITEMENT["paths"][path][method]


def at(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def viewer(repo):
    return bearer(repo.make("lecteur", Role.VIEWER))


def seed(indicators: FakeIndicatorRepository, count: int = 5, **changes):
    """`count` minutes consécutives, une fenêtre par minute, du plus ancien au plus récent."""
    indicators.rows += [make_row(window_start=at(n), **changes) for n in range(count)]


def assert_problem(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    check(body, PROBLEM)
    assert (body["status"], body["code"]) == (status, code)
    return body


# --- Le service décrit exactement ce que le contrat décrit -----------------------------------


def test_the_service_implements_the_three_indicator_operations_of_the_contract():
    paths = app.openapi()["paths"]
    for (path, method), operation_id in OPERATIONS.items():
        assert method in paths[path], path
        assert contract_operation(path, method)["operationId"] == operation_id
        assert paths[path][method]["x-required-role"] == "viewer"
        assert contract_operation(path, method)["x-required-role"] == "viewer"


COMMON = load(OPENAPI / "common.yaml")


def resolve(parameter: dict) -> dict:
    """Paramètre du contrat, avec sa référence à `common.yaml` remplacée par sa définition."""
    reference = parameter.get("$ref")
    if reference:
        return COMMON["components"]["parameters"][reference.rsplit("/", 1)[1]]
    return parameter


def declared_schema(definition: dict) -> dict:
    """Schéma d'un paramètre tel que FastAPI le décrit : sans `null`, références résolues."""
    candidates = definition.get("anyOf", [definition])
    candidate = next(c for c in candidates if c.get("type") != "null")
    while "$ref" in candidate:
        candidate = app.openapi()["components"]["schemas"][candidate["$ref"].rsplit("/", 1)[1]]
    return candidate


def schema_of(parameter: dict) -> dict:
    """Schéma d'un paramètre du contrat, références résolues, sans description ni exemple."""
    definition = parameter["schema"]
    while "$ref" in definition:
        fichier, _, chemin = definition["$ref"].partition("#")
        document = TRAITEMENT if fichier in ("", "traitement.openapi.yaml") else COMMON
        for part in chemin.strip("/").split("/"):
            document = document[part]
        definition = document
    return {k: v for k, v in definition.items() if k not in {"description", "examples", "example"}}


@pytest.mark.parametrize("path", ["/api/v1/indicators", "/api/v1/indicators/latest"])
def test_the_query_parameters_are_those_of_the_contract_with_the_same_bounds(path):
    declared = {p["name"]: p for p in app.openapi()["paths"][path]["get"].get("parameters", [])}
    expected = {}
    for parameter in contract_operation(path)["parameters"]:
        parameter = resolve(parameter)
        expected[parameter["name"]] = parameter
    assert set(declared) == set(expected)
    for name, parameter in expected.items():
        wanted, given = schema_of(parameter), declared_schema(declared[name]["schema"])
        for key in ("minimum", "maximum", "pattern", "minLength", "maxLength", "enum", "default"):
            if key in wanted:
                assert given.get(key) == wanted[key], f"{name}.{key}"
        assert declared[name].get("required", False) == parameter.get("required", False), name


# --- 401 : sans jeton valide -----------------------------------------------------------------


@pytest.mark.parametrize("path", [LIST, LATEST, "/api/v1/indicators/x:ROAD_001:60:0"])
def test_without_a_token_every_indicator_route_answers_401(client, path):
    response = client.get(path)
    assert_problem(response, 401, "UNAUTHENTICATED")
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("role", list(Role))
def test_every_role_can_read_indicators(client, repo, indicators, role):
    seed(indicators, 1)
    response = client.get(LIST, headers=bearer(repo.make("appelant", role)))
    assert response.status_code == 200


# --- Liste : réponses du contrat -------------------------------------------------------------


def test_the_list_is_a_page_of_the_contract(client, indicators, viewer):
    seed(indicators, 3)
    response = client.get(LIST, headers=viewer)
    assert response.status_code == 200
    body = response.json()
    check(body, PAGE)
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None


def test_the_example_of_the_contract_is_served_as_it_is_written(client, indicators, viewer):
    example = TRAITEMENT["components"]["schemas"]["Indicator"]["examples"][0]
    indicators.rows.append(make_row())
    served = client.get(LIST, headers=viewer).json()["items"][0]
    assert {k: v for k, v in served.items() if k != "provenance"} == {
        k: v for k, v in example.items() if k != "provenance"
    }
    assert served["indicator_id"] == example["indicator_id"]
    assert served["window_start"] == example["window_start"]


def test_the_items_are_sorted_by_window_start_descending_then_segment(client, indicators, viewer):
    indicators.rows += [
        make_row(window_start=at(0), road_segment_id="ROAD_002"),
        make_row(window_start=at(1), road_segment_id="ROAD_002"),
        make_row(window_start=at(1), road_segment_id="ROAD_001"),
        make_row(window_start=at(0), road_segment_id="ROAD_001"),
    ]
    ordre = [
        (i["window_start"], i["road_segment_id"])
        for i in client.get(LIST, headers=viewer).json()["items"]
    ]
    assert ordre == [
        (iso(at(1)), "ROAD_001"),
        (iso(at(1)), "ROAD_002"),
        (iso(at(0)), "ROAD_001"),
        (iso(at(0)), "ROAD_002"),
    ]


def test_an_empty_list_is_a_valid_empty_page(client, viewer):
    body = client.get(LIST, headers=viewer).json()
    check(body, PAGE)
    assert body == {"items": [], "next_cursor": None}


def test_nullable_measures_are_present_as_null_and_not_left_out(client, indicators, viewer):
    indicators.rows.append(
        make_row(
            vehicle_count=0,
            flow_veh_per_min=0.0,
            average_speed_kmh=None,
            speed_ratio=None,
            occupancy_rate=None,
            max_queue_length_m=None,
            congestion_state="FREE_FLOW",
        )
    )
    item = client.get(LIST, headers=viewer).json()["items"][0]
    check(item, INDICATOR)
    for name in ("average_speed_kmh", "speed_ratio", "occupancy_rate", "max_queue_length_m"):
        assert name in item and item[name] is None


def test_a_window_start_stored_with_another_offset_is_still_given_in_utc(
    client, indicators, viewer
):
    tokyo = timezone(timedelta(hours=9))
    indicators.rows.append(make_row(window_start=datetime(2026, 10, 20, 17, 20, tzinfo=tokyo)))
    item = client.get(LIST, headers=viewer).json()["items"][0]
    check(item, INDICATOR)
    assert item["window_start"] == "2026-10-20T08:20:00Z"


# --- Provenance ------------------------------------------------------------------------------


def test_a_simulated_indicator_carries_its_scenario_and_seed(client, indicators, viewer):
    indicators.rows.append(make_row())
    provenance = client.get(LIST, headers=viewer).json()["items"][0]["provenance"]
    assert provenance == {
        "source_type": "SIMULATED",
        "run_id": "run-demo-0001",
        "scenario_id": "journee-calme",
        "seed": 42,
    }


def test_a_historical_indicator_carries_its_dataset_and_nothing_empty(client, indicators, viewer):
    indicators.rows.append(
        make_row(source_type="REAL_HISTORICAL", scenario_id=None, seed=None, dataset_id="metr-la")
    )
    item = client.get(LIST, headers=viewer).json()["items"][0]
    check(item, INDICATOR)
    assert item["provenance"] == {
        "source_type": "REAL_HISTORICAL",
        "run_id": "run-demo-0001",
        "dataset_id": "metr-la",
    }


# --- Filtres de période et de zone -----------------------------------------------------------


def names(response) -> list[tuple[str, str]]:
    return [(i["road_segment_id"], i["window_start"]) for i in response.json()["items"]]


def test_the_period_includes_from_and_excludes_to(client, indicators, viewer):
    seed(indicators, 6)
    response = client.get(LIST, params={"from": iso(at(1)), "to": iso(at(4))}, headers=viewer)
    assert [w for _, w in names(response)] == [iso(at(3)), iso(at(2)), iso(at(1))]


def test_from_alone_and_to_alone_each_bound_one_side(client, indicators, viewer):
    seed(indicators, 4)
    depuis = client.get(LIST, params={"from": iso(at(2))}, headers=viewer)
    assert len(depuis.json()["items"]) == 2
    jusque = client.get(LIST, params={"to": iso(at(2))}, headers=viewer)
    assert len(jusque.json()["items"]) == 2


def test_a_period_with_fractional_seconds_is_accepted(client, indicators, viewer):
    seed(indicators, 2)
    response = client.get(LIST, params={"from": "2026-10-20T08:20:00.500000Z"}, headers=viewer)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_the_zone_filters_keep_one_intersection_or_one_segment(client, indicators, viewer):
    indicators.rows += [
        make_row(road_segment_id="ROAD_001", intersection_id="INT_01"),
        make_row(road_segment_id="ROAD_002", intersection_id="INT_01"),
        make_row(road_segment_id="ROAD_005", intersection_id="INT_02"),
    ]
    carrefour = client.get(LIST, params={"intersection_id": "INT_01"}, headers=viewer)
    assert {s for s, _ in names(carrefour)} == {"ROAD_001", "ROAD_002"}
    troncon = client.get(LIST, params={"road_segment_id": "ROAD_005"}, headers=viewer)
    assert {s for s, _ in names(troncon)} == {"ROAD_005"}
    combine = client.get(
        LIST, params={"intersection_id": "INT_01", "road_segment_id": "ROAD_005"}, headers=viewer
    )
    assert combine.json()["items"] == []


def test_the_window_size_defaults_to_one_minute_and_can_be_five(client, indicators, viewer):
    indicators.rows += [make_row(window_size_s=60), make_row(window_size_s=300)]
    assert [i["window_size_s"] for i in client.get(LIST, headers=viewer).json()["items"]] == [60]
    cinq = client.get(LIST, params={"window_size_s": 300}, headers=viewer)
    assert [i["window_size_s"] for i in cinq.json()["items"]] == [300]


def test_the_state_the_run_and_the_source_filters_each_apply(client, indicators, viewer):
    indicators.rows += [
        make_row(window_start=at(0), congestion_state="FREE_FLOW", run_id="run-a"),
        make_row(window_start=at(1), congestion_state="CONGESTED", run_id="run-a"),
        make_row(
            window_start=at(2),
            congestion_state="CONGESTED",
            run_id="run-b",
            source_type="REAL_HISTORICAL",
            scenario_id=None,
            seed=None,
            dataset_id="metr-la",
        ),
    ]
    état = client.get(LIST, params={"congestion_state": "CONGESTED"}, headers=viewer)
    assert len(état.json()["items"]) == 2
    run = client.get(LIST, params={"run_id": "run-a"}, headers=viewer)
    assert len(run.json()["items"]) == 2
    source = client.get(LIST, params={"source_type": "REAL_HISTORICAL"}, headers=viewer)
    assert [i["provenance"]["run_id"] for i in source.json()["items"]] == ["run-b"]
    tout = client.get(
        LIST,
        params={"congestion_state": "CONGESTED", "run_id": "run-a", "source_type": "SIMULATED"},
        headers=viewer,
    )
    assert len(tout.json()["items"]) == 1


# --- Pagination ------------------------------------------------------------------------------


def test_the_limit_caps_the_page_and_gives_a_cursor_when_more_remain(client, indicators, viewer):
    seed(indicators, 5)
    page = client.get(LIST, params={"limit": 2}, headers=viewer).json()
    check(page, PAGE)
    assert len(page["items"]) == 2
    assert page["next_cursor"]


def test_pages_follow_one_another_without_gap_or_overlap(client, indicators, viewer):
    for troncon in ("ROAD_001", "ROAD_002", "ROAD_003"):
        seed(indicators, 4, road_segment_id=troncon)
    vus, curseur, pages = [], None, 0
    while True:
        params = {"limit": 5} | ({"cursor": curseur} if curseur else {})
        page = client.get(LIST, params=params, headers=viewer).json()
        check(page, PAGE)
        vus += [i["indicator_id"] for i in page["items"]]
        pages += 1
        curseur = page["next_cursor"]
        if curseur is None:
            break
    attendu = [
        r.indicator_id
        for r in sorted(
            indicators.rows, key=lambda r: (-r.window_start.timestamp(), r.road_segment_id)
        )
    ]
    assert vus == attendu
    assert len(set(vus)) == 12
    assert pages == 3


def test_a_full_last_page_has_no_cursor(client, indicators, viewer):
    seed(indicators, 4)
    premiere = client.get(LIST, params={"limit": 2}, headers=viewer).json()
    derniere = client.get(
        LIST, params={"limit": 2, "cursor": premiere["next_cursor"]}, headers=viewer
    ).json()
    assert len(derniere["items"]) == 2
    assert derniere["next_cursor"] is None


def test_the_cursor_keeps_working_when_windows_share_the_same_start(client, indicators, viewer):
    indicators.rows += [make_row(road_segment_id=f"ROAD_00{n}") for n in range(1, 6)]
    vus, curseur = [], None
    while True:
        params = {"limit": 2} | ({"cursor": curseur} if curseur else {})
        page = client.get(LIST, params=params, headers=viewer).json()
        vus += [i["road_segment_id"] for i in page["items"]]
        curseur = page["next_cursor"]
        if curseur is None:
            break
    assert vus == [f"ROAD_00{n}" for n in range(1, 6)]


def test_the_default_limit_is_one_hundred(client, indicators, viewer):
    seed(indicators, 101)
    page = client.get(LIST, headers=viewer).json()
    assert len(page["items"]) == 100
    assert page["next_cursor"] is not None


# --- 422 : entrées hors contrat --------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "query.limit"),
        ({"limit": 501}, "query.limit"),
        ({"limit": "beaucoup"}, "query.limit"),
        ({"cursor": "x" * 513}, "query.cursor"),
        ({"intersection_id": "carrefour-1"}, "query.intersection_id"),
        ({"intersection_id": "INT_1"}, "query.intersection_id"),
        ({"road_segment_id": "ROAD_1"}, "query.road_segment_id"),
        ({"from": "2026-10-20"}, "query.from"),
        ({"from": "2026-10-20T08:20:00+02:00"}, "query.from"),
        ({"from": "hier"}, "query.from"),
        ({"to": "2026-10-20T08:20:00"}, "query.to"),
        ({"window_size_s": 120}, "query.window_size_s"),
        ({"window_size_s": "x"}, "query.window_size_s"),
        ({"congestion_state": "BLOQUE"}, "query.congestion_state"),
        ({"run_id": ""}, "query.run_id"),
        ({"run_id": "r" * 81}, "query.run_id"),
        ({"source_type": "REEL"}, "query.source_type"),
    ],
)
def test_a_parameter_outside_the_contract_gives_a_problem_422_naming_the_field(
    client, viewer, params, field
):
    body = assert_problem(client.get(LIST, params=params, headers=viewer), 422, "VALIDATION_ERROR")
    assert [e["field"] for e in body["errors"]] == [field]
    assert all(e["message"] and "Traceback" not in e["message"] for e in body["errors"])


def test_an_impossible_date_gives_a_problem_422(client, viewer):
    response = client.get(LIST, params={"from": "2026-02-30T00:00:00Z"}, headers=viewer)
    body = assert_problem(response, 422, "VALIDATION_ERROR")
    assert body["errors"][0]["field"] == "query.from"


def test_a_period_that_ends_before_it_starts_gives_a_problem_422(client, viewer):
    for debut, fin in ((at(5), at(5)), (at(5), at(2))):
        response = client.get(LIST, params={"from": iso(debut), "to": iso(fin)}, headers=viewer)
        body = assert_problem(response, 422, "VALIDATION_ERROR")
        assert body["errors"] == [
            {"field": "query.to", "message": "Doit être postérieure à `from`."}
        ]


def test_a_cursor_that_this_service_did_not_make_gives_a_problem_422(client, viewer):
    for curseur in ("n-importe-quoi", "YWJj", "WyJhIl0", "eyJhIjoxfQ"):
        response = client.get(LIST, params={"cursor": curseur}, headers=viewer)
        body = assert_problem(response, 422, "VALIDATION_ERROR")
        assert body["errors"][0]["field"] == "query.cursor"


def test_several_wrong_parameters_are_all_reported(client, viewer):
    response = client.get(LIST, params={"limit": 0, "window_size_s": 7}, headers=viewer)
    body = assert_problem(response, 422, "VALIDATION_ERROR")
    assert {e["field"] for e in body["errors"]} == {"query.limit", "query.window_size_s"}
    assert body["detail"] == "2 champs invalides."


# --- Détail ----------------------------------------------------------------------------------


def test_a_known_indicator_is_read_by_its_identifier(client, indicators, viewer):
    seed(indicators, 3)
    cible = client.get(LIST, headers=viewer).json()["items"][1]
    response = client.get(f"/api/v1/indicators/{cible['indicator_id']}", headers=viewer)
    assert response.status_code == 200
    check(response.json(), INDICATOR)
    assert response.json() == cible


def test_the_identifier_of_the_contract_example_is_found(client, indicators, viewer):
    indicators.rows.append(make_row())
    identifiant = TRAITEMENT["paths"]["/api/v1/indicators/{indicator_id}"]["get"]["parameters"][0][
        "example"
    ]
    response = client.get(f"/api/v1/indicators/{identifiant}", headers=viewer)
    assert response.status_code == 200
    assert response.json()["indicator_id"] == identifiant


def test_a_run_identifier_that_contains_colons_does_not_break_the_lookup(
    client, indicators, viewer
):
    indicators.rows.append(make_row(run_id="run:2026:10:20"))
    identifiant = indicators.rows[0].indicator_id
    assert identifiant.startswith("run:2026:10:20:ROAD_001:60:")
    assert client.get(f"/api/v1/indicators/{identifiant}", headers=viewer).status_code == 200


@pytest.mark.parametrize(
    "identifiant",
    [
        "run-demo-0001:ROAD_001:60:1",
        "run-demo-0001:ROAD_999:60:1792484400000",
        "run-demo-0001:ROAD_001:300:1792484400000",
        "run-demo-0001:ROAD_001:120:1792484400000",
        "run-demo-0001:ROAD_001:60:-5",
        "run-demo-0001:ROAD_001:60:abc",
        "run-demo-0001:ROAD_001:60:99999999999999999999999",
        "ROAD_001:60:1792484400000",
        "n-importe-quoi",
        "a:ROAD_001:60:١٢٣",
        "x" * 300,
    ],
)
def test_an_unknown_or_malformed_identifier_gives_a_problem_404(
    client, indicators, viewer, identifiant
):
    indicators.rows.append(make_row())
    assert_problem(
        client.get(f"/api/v1/indicators/{identifiant}", headers=viewer), 404, "NOT_FOUND"
    )


# --- Dernier indicateur de chaque tronçon ----------------------------------------------------


def test_latest_gives_one_minute_window_per_segment_the_most_recent(client, indicators, viewer):
    for troncon in ("ROAD_002", "ROAD_001"):
        seed(indicators, 3, road_segment_id=troncon)
    indicators.rows.append(make_row(window_start=at(9), window_size_s=300))
    response = client.get(LATEST, headers=viewer)
    assert response.status_code == 200
    body = response.json()
    check(
        body,
        "traitement.openapi.yaml#/paths/~1api~1v1~1indicators~1latest/get/responses/200/content/application~1json/schema",
    )
    assert [
        (i["road_segment_id"], i["window_start"], i["window_size_s"]) for i in body["items"]
    ] == [
        ("ROAD_001", iso(at(2)), 60),
        ("ROAD_002", iso(at(2)), 60),
    ]


def test_latest_reads_the_most_recent_run_by_default_and_any_run_on_request(
    client, indicators, viewer
):
    indicators.rows += [
        make_row(window_start=at(0), run_id="run-ancien"),
        make_row(window_start=at(5), run_id="run-recent"),
    ]
    assert [
        i["provenance"]["run_id"] for i in client.get(LATEST, headers=viewer).json()["items"]
    ] == ["run-recent"]
    ancien = client.get(LATEST, params={"run_id": "run-ancien"}, headers=viewer)
    assert [i["provenance"]["run_id"] for i in ancien.json()["items"]] == ["run-ancien"]
    assert client.get(LATEST, params={"run_id": "inconnu"}, headers=viewer).json() == {"items": []}


def test_latest_can_be_limited_to_one_intersection(client, indicators, viewer):
    indicators.rows += [
        make_row(road_segment_id="ROAD_001", intersection_id="INT_01"),
        make_row(road_segment_id="ROAD_005", intersection_id="INT_02"),
    ]
    reponse = client.get(LATEST, params={"intersection_id": "INT_02"}, headers=viewer)
    assert [i["road_segment_id"] for i in reponse.json()["items"]] == ["ROAD_005"]


def test_latest_is_an_empty_list_without_data_and_rejects_bad_parameters(client, viewer):
    assert client.get(LATEST, headers=viewer).json() == {"items": []}
    body = assert_problem(
        client.get(LATEST, params={"intersection_id": "x"}, headers=viewer), 422, "VALIDATION_ERROR"
    )
    assert body["errors"][0]["field"] == "query.intersection_id"


def test_latest_is_not_taken_for_an_indicator_identifier(client, indicators, viewer):
    indicators.rows.append(make_row())
    assert "items" in client.get(LATEST, headers=viewer).json()


# --- Lecture seule ---------------------------------------------------------------------------


def test_no_indicator_route_accepts_a_write(client, viewer):
    for method in ("post", "put", "patch", "delete"):
        for path in (LIST, LATEST, "/api/v1/indicators/x"):
            assert getattr(client, method)(path, headers=viewer).status_code in (405, 404, 401)


def test_an_unconfigured_warehouse_gives_a_503_problem_not_a_stack_trace(secret, repo, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.db import session as session_module
    from app.db.session import get_user_repository

    monkeypatch.delenv("POSTGRES_URL", raising=False)
    get_settings.cache_clear()
    session_module.get_warehouse_session_factory.cache_clear()
    app.dependency_overrides[get_user_repository] = lambda: repo
    try:
        reponse = TestClient(app).get(LIST, headers=bearer(repo.make("lecteur", Role.VIEWER)))
    finally:
        app.dependency_overrides.clear()
    assert_problem(reponse, 503, "UPSTREAM_UNAVAILABLE")
