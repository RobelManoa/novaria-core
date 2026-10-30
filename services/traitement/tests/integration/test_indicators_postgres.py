"""Lecture des indicateurs contre un vrai PostgreSQL migré par les migrations SQL du dépôt (BE-04).

Trois choses que les tests sans base ne peuvent pas prouver :
- la vue `dwh.v_indicator` et la migration `0007` (provenance, contraintes de `dim_run`) ;
- l'accord du dépôt SQL et du dépôt en mémoire : mêmes filtres, même ordre, mêmes pages ;
- les réponses de l'API, sur de vraies lignes, respectent le contrat OpenAPI.
Ignoré sans `NOVARIA_TEST_POSTGRES_ADMIN_URL` (voir `tests/integration/postgres.py`).
"""

import itertools
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import READ_ONLY, get_indicator_repository, get_user_repository
from app.main import app
from app.models import Role
from app.repositories.indicators import IndicatorFilters, SqlIndicatorRepository
from app.services.indicators import IndicatorService, make_indicator_id
from tests.fakes import SECRET, FakeIndicatorRepository, FakeUserRepository, bearer
from tests.integration.postgres import needs_postgres
from tests.openapi_checks import PROBLEM, TRAITEMENT, check, schema

pytestmark = needs_postgres

DEBUT = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
MINUTES = 6
TRONCONS = ["ROAD_001", "ROAD_002", "ROAD_005"]  # INT_01, INT_01, INT_02 du réseau de démonstration
ETATS = ["FREE_FLOW", "SLOW", "CONGESTED"]

INSERT_RUN = text(
    "INSERT INTO dwh.dim_run (run_id, source_type, scenario_id, seed, dataset_id) "
    "VALUES (:run_id, :source_type, :scenario_id, :seed, :dataset_id)"
)
INSERT_FACT = text(
    """
    INSERT INTO dwh.fact_traffic_window
        (road_segment_key, window_start, window_size_s, run_id, source_type, vehicle_count,
         flow_veh_per_min, average_speed_kmh, occupancy_rate, speed_ratio, sample_count,
         expected_sample_count, congestion_state, classifier_version)
    SELECT s.road_segment_key, :start, :size, :run_id, :source_type, :vehicles, :flow, :speed,
           :occupancy, :ratio, 6, 6, :state, 'regles-v0'
    FROM dwh.dim_road_segment s WHERE s.road_segment_id = :segment
    """
)


def seed(engine) -> None:
    """Deux exécutions enregistrées (simulée, historique) et une troisième qui ne l'est pas."""
    with engine.begin() as connexion:
        connexion.execute(
            INSERT_RUN,
            {
                "run_id": "run-a",
                "source_type": "SIMULATED",
                "scenario_id": "journee-calme",
                "seed": 7,
                "dataset_id": None,
            },
        )
        connexion.execute(
            INSERT_RUN,
            {
                "run_id": "run_b",
                "source_type": "REAL_HISTORICAL",
                "scenario_id": None,
                "seed": None,
                "dataset_id": "metr-la",
            },
        )
        for run, source in (
            ("run-a", "SIMULATED"),
            ("run_b", "REAL_HISTORICAL"),
            ("run-orphelin", "SIMULATED"),
        ):
            for (minute, troncon), taille in itertools.product(
                itertools.product(range(MINUTES), TRONCONS), (60, 300)
            ):
                numero = minute + len(troncon) + (3 if run == "run_b" else 0)
                vide = numero % 5 == 0
                connexion.execute(
                    INSERT_FACT,
                    {
                        "start": DEBUT + timedelta(minutes=minute * (5 if taille == 300 else 1)),
                        "size": taille,
                        "run_id": run,
                        "source_type": source,
                        "segment": troncon,
                        "vehicles": 0 if vide else 4 + numero,
                        "flow": 0 if vide else (4 + numero) / (taille / 60),
                        "speed": None if vide else 10 + numero,
                        "occupancy": None if vide else 0.1 * (numero % 9),
                        "ratio": None if vide else round((10 + numero) / 50, 3),
                        "state": "FREE_FLOW" if vide else ETATS[numero % 3],
                    },
                )


@pytest.fixture
def seeded(warehouse):
    seed(warehouse)
    return warehouse


@pytest.fixture
def repository(seeded):
    with Session(seeded) as session:
        yield SqlIndicatorRepository(session)


def tout_lire(repository, **filtres):
    """Toutes les lignes d'un filtre, par pages de 1000 (le dépôt sait déjà les ordonner)."""
    return repository.list_page(IndicatorFilters(**filtres), limit=1000, after=None)


# --- Migration 0007 --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valeurs", "contrainte"),
    [
        (
            {"source_type": "SIMULATED", "scenario_id": None, "seed": 1},
            "dim_run_simulated_needs_scenario_and_seed",
        ),
        (
            {"source_type": "SIMULATED", "scenario_id": "calme", "seed": None},
            "dim_run_simulated_needs_scenario_and_seed",
        ),
        (
            {"source_type": "REAL_HISTORICAL", "dataset_id": None},
            "dim_run_historical_needs_dataset",
        ),
        (
            {"source_type": "SIMULATED", "scenario_id": "Majuscule", "seed": 1},
            "dim_run_scenario_id_check",
        ),
        ({"source_type": "SIMULATED", "scenario_id": "calme", "seed": -1}, "dim_run_seed_check"),
        ({"source_type": "REAL_HISTORICAL", "dataset_id": "MAJUSCULE"}, "dim_run_dataset_id_check"),
        ({"source_type": "INCONNU", "scenario_id": "calme", "seed": 1}, "dim_run_source_type_fkey"),
        ({"run_id": ""}, "dim_run_run_id_check"),
    ],
)
def test_a_run_that_breaks_the_provenance_rules_is_refused(warehouse, valeurs, contrainte):
    ligne = {
        "run_id": "r",
        "source_type": "SIMULATED",
        "scenario_id": "calme",
        "seed": 1,
        "dataset_id": None,
    } | valeurs
    with pytest.raises(IntegrityError) as erreur, warehouse.begin() as connexion:
        connexion.execute(INSERT_RUN, ligne)
    assert contrainte in str(erreur.value)


def test_a_valid_run_of_each_kind_is_accepted_and_a_run_is_unique(warehouse):
    with warehouse.begin() as connexion:
        connexion.execute(
            INSERT_RUN,
            {
                "run_id": "live",
                "source_type": "REAL_LIVE",
                "scenario_id": None,
                "seed": None,
                "dataset_id": None,
            },
        )
        connexion.execute(
            INSERT_RUN,
            {
                "run_id": "s",
                "source_type": "SIMULATED",
                "scenario_id": "calme",
                "seed": 0,
                "dataset_id": None,
            },
        )
    with pytest.raises(IntegrityError), warehouse.begin() as connexion:
        connexion.execute(
            INSERT_RUN,
            {
                "run_id": "s",
                "source_type": "SIMULATED",
                "scenario_id": "x",
                "seed": 1,
                "dataset_id": None,
            },
        )


def test_only_registered_runs_with_a_matching_source_type_appear_in_the_view(seeded):
    with seeded.connect() as connexion:
        runs = (
            connexion.execute(text("SELECT DISTINCT run_id FROM dwh.v_indicator ORDER BY 1"))
            .scalars()
            .all()
        )
        assert runs == ["run-a", "run_b"], "run-orphelin n'est pas enregistré : il n'est pas servi"
        total = connexion.execute(text("SELECT count(*) FROM dwh.fact_traffic_window")).scalar()
        assert total == 3 * len(TRONCONS) * MINUTES * 2
        servi = connexion.execute(text("SELECT count(*) FROM dwh.v_indicator")).scalar()
        assert servi == 2 * len(TRONCONS) * MINUTES * 2
    with seeded.begin() as connexion:
        connexion.execute(
            text("UPDATE dwh.dim_run SET source_type = 'REAL_LIVE' WHERE run_id = 'run-a'")
        )
    with seeded.connect() as connexion:
        runs = (
            connexion.execute(text("SELECT DISTINCT run_id FROM dwh.v_indicator")).scalars().all()
        )
        assert runs == ["run_b"], "un type de source différent de celui des faits n'est pas servi"


def test_the_identifier_built_by_the_view_is_the_one_built_by_python(repository):
    lignes = tout_lire(repository, window_size_s=60) + tout_lire(repository, window_size_s=300)
    assert len(lignes) == 2 * len(TRONCONS) * MINUTES * 2
    for ligne in lignes:
        assert ligne.indicator_id == make_indicator_id(
            ligne.run_id, ligne.road_segment_id, ligne.window_size_s, ligne.window_start
        )


# --- Accord du dépôt SQL et du dépôt en mémoire ----------------------------------------------

FILTRES = [
    {},
    {"window_size_s": 300},
    {"intersection_id": "INT_01"},
    {"intersection_id": "INT_02", "window_size_s": 300},
    {"road_segment_id": "ROAD_002"},
    {"congestion_state": "CONGESTED"},
    {"congestion_state": "FREE_FLOW", "road_segment_id": "ROAD_001"},
    {"run_id": "run_b"},
    {"run_id": "run-a", "source_type": "SIMULATED"},
    {"source_type": "REAL_HISTORICAL"},
    {"start": DEBUT + timedelta(minutes=2)},
    {"end": DEBUT + timedelta(minutes=3)},
    {"start": DEBUT + timedelta(minutes=1), "end": DEBUT + timedelta(minutes=4)},
    {"start": DEBUT + timedelta(minutes=2), "end": DEBUT + timedelta(minutes=2)},
    {
        "window_size_s": 300,
        "start": DEBUT + timedelta(minutes=5),
        "end": DEBUT + timedelta(minutes=15),
    },
]


@pytest.fixture
def jumeau(repository):
    """Le dépôt en mémoire chargé des mêmes lignes que la base."""
    lignes = tout_lire(repository, window_size_s=60) + tout_lire(repository, window_size_s=300)
    return FakeIndicatorRepository(lignes)


@pytest.mark.parametrize("filtres", FILTRES, ids=[str(f) for f in FILTRES])
def test_the_sql_and_in_memory_repositories_give_the_same_pages(repository, jumeau, filtres):
    for limite in (1, 4, 1000):
        sql, memoire, position = [], [], None
        while True:
            reel = repository.list_page(IndicatorFilters(**filtres), limit=limite, after=position)
            attendu = jumeau.list_page(IndicatorFilters(**filtres), limit=limite, after=position)
            assert [r.indicator_id for r in reel] == [r.indicator_id for r in attendu]
            sql += reel
            if len(reel) < limite:
                break
            derniere = reel[-1]
            position = (derniere.window_start, derniere.road_segment_id, derniere.run_id)
        assert len({r.indicator_id for r in sql}) == len(sql), "aucun doublon entre deux pages"
        memoire = jumeau.list_page(IndicatorFilters(**filtres), limit=10_000, after=None)
        assert [r.indicator_id for r in sql] == [r.indicator_id for r in memoire]


def test_the_two_repositories_agree_on_the_latest_indicators_too(repository, jumeau):
    for arguments in (
        {"intersection_id": None, "run_id": None},
        {"intersection_id": "INT_01", "run_id": None},
        {"intersection_id": None, "run_id": "run-a"},
        {"intersection_id": "INT_02", "run_id": "run_b"},
        {"intersection_id": None, "run_id": "inconnu"},
    ):
        reel = repository.latest(**arguments)
        assert [r.indicator_id for r in reel] == [
            r.indicator_id for r in jumeau.latest(**arguments)
        ], arguments
    assert len(repository.latest(intersection_id=None, run_id="run-a")) == len(TRONCONS)


def test_the_order_of_run_identifiers_is_the_byte_order_whatever_the_database_collation(repository):
    lignes = tout_lire(repository, window_size_s=60)
    memes_instants = [
        r
        for r in lignes
        if r.window_start == lignes[0].window_start and r.road_segment_id == "ROAD_001"
    ]
    assert [r.run_id for r in memes_instants] == ["run-a", "run_b"], (
        "« - » (0x2d) avant « _ » (0x5f)"
    )


def test_get_reads_one_indicator_by_its_four_part_key(repository):
    ligne = tout_lire(repository, run_id="run_b", road_segment_id="ROAD_005")[2]
    lue = repository.get(
        run_id=ligne.run_id,
        road_segment_id=ligne.road_segment_id,
        window_size_s=ligne.window_size_s,
        window_start=ligne.window_start,
    )
    assert lue == ligne
    assert (
        repository.get(
            run_id="run-orphelin", road_segment_id="ROAD_001", window_size_s=60, window_start=DEBUT
        )
        is None
    )


# --- Lecture seule ---------------------------------------------------------------------------


def test_the_read_only_connection_refuses_any_write(seeded):
    moteur = create_engine(seeded.url, connect_args=READ_ONLY)
    try:
        with moteur.connect() as connexion:
            assert connexion.execute(text("SELECT count(*) FROM dwh.v_indicator")).scalar() > 0
            with pytest.raises(DBAPIError) as erreur:
                connexion.execute(text("DELETE FROM dwh.fact_traffic_window"))
            assert "read-only transaction" in str(erreur.value)
    finally:
        moteur.dispose()
    with seeded.connect() as connexion:
        assert connexion.execute(text("SELECT count(*) FROM dwh.fact_traffic_window")).scalar() > 0


# --- Réponses de l'API sur de vraies lignes --------------------------------------------------


@pytest.fixture
def client(seeded, monkeypatch):
    """L'application complète, lisant l'entrepôt avec une session de base en fuseau de Tokyo."""
    monkeypatch.setenv("JWT_SECRET", SECRET)
    get_settings.cache_clear()
    moteur = create_engine(seeded.url, connect_args={"options": "-c timezone=Asia/Tokyo"})
    comptes = FakeUserRepository()

    def entrepot():
        with Session(moteur) as session:
            yield SqlIndicatorRepository(session)

    app.dependency_overrides[get_indicator_repository] = entrepot
    app.dependency_overrides[get_user_repository] = lambda: comptes
    try:
        yield TestClient(app), bearer(comptes.make("lecteur", Role.VIEWER))
    finally:
        app.dependency_overrides.clear()
        moteur.dispose()
        get_settings.cache_clear()


def test_every_row_served_by_the_api_respects_the_contract(client):
    http, en_tete = client
    vus, curseur = 0, None
    while True:
        params = {"limit": 50, "window_size_s": 300} | ({"cursor": curseur} if curseur else {})
        page = http.get("/api/v1/indicators", params=params, headers=en_tete)
        assert page.status_code == 200
        check(page.json(), schema("IndicatorPage", "traitement"))
        for item in page.json()["items"]:
            assert item["window_start"].endswith("Z")
        vus += len(page.json()["items"])
        curseur = page.json()["next_cursor"]
        if curseur is None:
            break
    assert vus == 2 * len(TRONCONS) * MINUTES


def test_provenance_comes_from_the_run_table(client):
    http, en_tete = client
    simule = http.get(
        "/api/v1/indicators", params={"run_id": "run-a", "limit": 1}, headers=en_tete
    ).json()["items"][0]
    historique = http.get(
        "/api/v1/indicators", params={"run_id": "run_b", "limit": 1}, headers=en_tete
    ).json()["items"][0]
    assert simule["provenance"] == {
        "source_type": "SIMULATED",
        "run_id": "run-a",
        "scenario_id": "journee-calme",
        "seed": 7,
    }
    assert historique["provenance"] == {
        "source_type": "REAL_HISTORICAL",
        "run_id": "run_b",
        "dataset_id": "metr-la",
    }


def test_detail_and_latest_on_real_rows_respect_the_contract(client):
    http, en_tete = client
    premier = http.get("/api/v1/indicators", params={"run_id": "run-a"}, headers=en_tete).json()[
        "items"
    ][3]
    detail = http.get(f"/api/v1/indicators/{premier['indicator_id']}", headers=en_tete)
    assert detail.status_code == 200
    check(detail.json(), schema("Indicator", "traitement"))
    assert detail.json() == premier
    dernier = http.get("/api/v1/indicators/latest", headers=en_tete)
    assert dernier.status_code == 200
    assert len(dernier.json()["items"]) == len(TRONCONS)
    for item in dernier.json()["items"]:
        check(item, schema("Indicator", "traitement"))
    inconnu = http.get("/api/v1/indicators/run-orphelin:ROAD_001:60:1792483200000", headers=en_tete)
    assert inconnu.status_code == 404
    check(inconnu.json(), PROBLEM)


def test_a_null_speed_stays_null_through_the_view_and_the_api(client):
    http, en_tete = client
    items = http.get("/api/v1/indicators", params={"limit": 500}, headers=en_tete).json()["items"]
    vides = [i for i in items if i["vehicle_count"] == 0]
    assert vides, "le jeu contient des fenêtres sans véhicule"
    assert all(i["average_speed_kmh"] is None and i["speed_ratio"] is None for i in vides)
    assert all(i["average_speed_kmh"] is not None for i in items if i["vehicle_count"] > 0)


def test_the_service_reads_the_period_and_zone_filters_on_the_real_view(repository):
    service = IndicatorService(repository)
    page = service.list_page(
        IndicatorFilters(
            intersection_id="INT_01",
            start=DEBUT + timedelta(minutes=1),
            end=DEBUT + timedelta(minutes=3),
            run_id="run-a",
        ),
        limit=100,
    )
    assert {r.road_segment_id for r in page.items} == {"ROAD_001", "ROAD_002"}
    assert {r.window_start for r in page.items} == {
        DEBUT + timedelta(minutes=1),
        DEBUT + timedelta(minutes=2),
    }
    assert TRAITEMENT["info"]["title"]
