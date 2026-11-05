"""MS-10, critère : les indicateurs servis par l'API sont identiques à un recalcul SQL de référence.

La chaîne complète, sur un vrai PostgreSQL migré par les migrations du dépôt :

    mesures brutes -> service de flux -> indicateurs -> pipeline d'écriture -> entrepôt -> API

puis, à côté, un recalcul SQL **indépendant** (`reference/indicateurs.sql`) sur les mêmes mesures
brutes, sans une ligne du code Python du service. Chaque champ de chaque fenêtre servie par l'API
est comparé à ce recalcul, exactement (décimaux, pas de tolérance).

Ignoré sans `NOVARIA_TEST_POSTGRES_ADMIN_URL` : `dev.py test-integration` (projet Compose jetable).
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_indicator_repository, get_user_repository
from app.flux.adapters.warehouse import Warehouse
from app.flux.processor import Processor
from app.main import app
from app.models import Role
from app.pipeline.adapters.postgres import WarehouseWriter
from app.pipeline.processor import Pipeline
from app.pipeline.recommender import Recommender
from app.repositories.indicators import SqlIndicatorRepository
from tests.fakes import SECRET, FakeUserRepository, bearer
from tests.integration.postgres import needs_postgres
from tests.integration.scenario import RUN, generate
from tests.unit.flux.support import Clock, FakeArchive, FakeEpisodes, FakePublisher, FakeStats

pytestmark = needs_postgres

REFERENCE_SQL = Path(__file__).parent / "reference" / "indicateurs.sql"
COMPARED = (
    "vehicle_count", "flow_veh_per_min", "average_speed_kmh", "occupancy_rate",
    "max_queue_length_m", "speed_ratio", "sample_count", "expected_sample_count",
    "completeness", "congestion_state",
)  # fmt: skip

CREATE_REFERENCE_TABLE = text(
    """
    CREATE TABLE public.ref_measurements (
        id text PRIMARY KEY, sensor_id text NOT NULL, road_segment_id text NOT NULL,
        run_id text NOT NULL, end_time timestamptz NOT NULL, interval_s integer NOT NULL,
        vehicle_count integer NOT NULL, speed numeric, occupancy numeric, queue numeric,
        status text NOT NULL
    )
    """
)
INSERT_REFERENCE = text(
    """
    INSERT INTO public.ref_measurements VALUES
        (:id, :sensor_id, :road_segment_id, :run_id, :end_time, :interval_s, :vehicle_count,
         :speed, :occupancy, :queue, :status)
    """
)


def url_of(engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def decimal(value) -> Decimal | None:
    return None if value is None else Decimal(repr(value))


def fill_reference_table(engine, messages: list[dict]) -> None:
    """Les mêmes mesures brutes, en décimaux exacts, dans une table lue par le recalcul SQL."""
    rows = []
    for m in messages:
        d = m["data"]
        rows.append(
            {
                "id": m["id"], "sensor_id": d["sensor_id"], "road_segment_id": d["road_segment_id"],
                "run_id": d["provenance"]["run_id"],
                "end_time": datetime.fromisoformat(m["time"].replace("Z", "+00:00")),
                "interval_s": d["interval_s"], "vehicle_count": d["vehicle_count"],
                "speed": decimal(d["average_speed_kmh"]), "occupancy": decimal(d["occupancy_rate"]),
                "queue": decimal(d["queue_length_m"]), "status": d["quality"]["status"],
            }
        )  # fmt: skip
    with engine.begin() as connection:
        connection.execute(CREATE_REFERENCE_TABLE)
        connection.execute(INSERT_REFERENCE, rows)


def run_chain(engine, messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Flux puis pipeline d'écriture, vrais adaptateurs de base, bus et MongoDB en mémoire."""
    clock = Clock()
    published = FakePublisher()
    warehouse = Warehouse(url_of(engine))
    processor = Processor(
        warehouse.load_referential(), published, FakeArchive(), FakeEpisodes(), FakeStats(),
        clock=clock, utc_now=clock.utc_now,
    )  # fmt: skip
    for offset, m in enumerate(messages):
        processor.handle(json.dumps(m).encode(), m["subject"].encode(), 0, offset)
    indicators = published.on("traffic.indicators")

    writer = WarehouseWriter(url_of(engine))
    recommendations = FakePublisher()
    pipeline = Pipeline(
        writer, Recommender(writer.load_plan_reference()), recommendations, FakeArchive(),
        FakeStats(), clock=clock, utc_now=clock.utc_now,
    )  # fmt: skip
    for offset, event in enumerate(indicators):
        pipeline.handle(json.dumps(event).encode(), event["subject"].encode(), 0, offset)
    pipeline.checkpoint()
    writer.close()
    warehouse.close()
    return indicators, recommendations.on("traffic.recommendations")


@pytest.fixture
def chain(warehouse):
    messages = generate()
    fill_reference_table(warehouse, messages)
    indicators, recommendations = run_chain(warehouse, messages)
    return warehouse, messages, indicators, recommendations


@pytest.fixture
def api(chain, monkeypatch):
    """L'application complète, lisant l'entrepôt par le dépôt SQL (session en lecture seule)."""
    engine = chain[0]
    monkeypatch.setenv("JWT_SECRET", SECRET)
    get_settings.cache_clear()
    accounts = FakeUserRepository()
    read_engine = create_engine(
        url_of(engine), connect_args={"options": "-c default_transaction_read_only=on"}
    )

    def repository():
        with Session(read_engine) as session:
            yield SqlIndicatorRepository(session)

    app.dependency_overrides[get_indicator_repository] = repository
    app.dependency_overrides[get_user_repository] = lambda: accounts
    try:
        yield TestClient(app), bearer(accounts.make("lecteur", Role.VIEWER))
    finally:
        app.dependency_overrides.clear()
        read_engine.dispose()
        get_settings.cache_clear()


def served(api, size: int) -> dict[tuple[str, str], dict]:
    """Tout ce que l'API sert pour le run d'essai et une taille de fenêtre, page après page."""
    http, headers = api
    rows, cursor = {}, None
    while True:
        params = {"run_id": RUN, "window_size_s": size, "limit": 500}
        if cursor:
            params["cursor"] = cursor
        page = http.get("/api/v1/indicators", params=params, headers=headers)
        assert page.status_code == 200, page.text
        body = page.json()
        for item in body["items"]:
            key = (item["road_segment_id"], item["window_start"])
            assert key not in rows, f"fenêtre servie deux fois : {key}"
            rows[key] = item
        cursor = body.get("next_cursor")
        if not cursor:
            return rows


def reference_rows(engine) -> list[dict]:
    with engine.connect() as connection:
        result = connection.execute(text(REFERENCE_SQL.read_text(encoding="utf-8")))
        return [dict(row._mapping) for row in result]


def one_minute(engine) -> dict[tuple[str, str], dict]:
    return {
        (r["road_segment_id"], iso(r["window_start"])): r
        for r in reference_rows(engine)
        if r["window_size_s"] == 60
    }


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def same(served_value, reference_value) -> bool:
    if reference_value is None or served_value is None:
        return reference_value is None and served_value is None
    if isinstance(reference_value, str):
        return served_value == reference_value
    return Decimal(repr(served_value)) == Decimal(reference_value)


def scalar_row(engine, sql: str, **parameters):
    with engine.connect() as connection:
        return tuple(connection.execute(text(sql), parameters).one())


@pytest.mark.parametrize("size", [60, 300])
def test_les_indicateurs_servis_par_l_api_sont_ceux_du_recalcul_sql(chain, api, size):
    engine, *_ = chain
    reference = {
        (r["road_segment_id"], iso(r["window_start"])): r
        for r in reference_rows(engine)
        if r["window_size_s"] == size
    }
    api_rows = served(api, size)

    # 1. tout ce que l'API sert existe dans le recalcul, champ par champ, sans tolérance
    differences = []
    for key, item in api_rows.items():
        assert key in reference, f"l'API sert une fenêtre que le recalcul ne connaît pas : {key}"
        for field in COMPARED:
            if not same(item[field], reference[key][field]):
                differences.append((key, field, item[field], reference[key][field]))
    assert differences == []

    # 2. tout ce que le recalcul ferme est servi, sauf les fenêtres retenues par le contrat
    #    (état dégradé sans vitesse donc sans ratio : on n'invente pas de ratio)
    missing = [k for k, row in reference.items() if row["closed"] and k not in api_rows]
    for key in missing:
        row = reference[key]
        assert row["congestion_state"] in ("SLOW", "CONGESTED") and row["speed_ratio"] is None, key
    assert len(api_rows) + len(missing) == sum(r["closed"] for r in reference.values())

    # 3. et rien n'est servi avant d'être fermé
    assert all(reference[key]["closed"] for key in api_rows)


def test_le_jeu_de_test_exerce_bien_les_cas_difficiles(chain, api):
    """Garde-fou : si le jeu perdait ses cas piégeux, la comparaison ne prouverait plus rien."""
    engine, *_ = chain
    reference = one_minute(engine)
    served_rows = served(api, 60)
    closed_states = {r["congestion_state"] for r in reference.values() if r["closed"]}

    assert closed_states == {"UNKNOWN", "FREE_FLOW", "SLOW", "CONGESTED"}
    tie_occupancy = ("ROAD_002", "2026-10-20T08:10:00Z")  # moyenne exacte 0,3125
    tie_speed = ("ROAD_004", "2026-10-20T08:25:00Z")  # moyenne exacte 38,25
    assert reference[tie_occupancy]["occupancy_rate"] == Decimal("0.313")
    assert reference[tie_speed]["average_speed_kmh"] == Decimal("38.3")
    assert served_rows[tie_occupancy]["occupancy_rate"] == 0.313
    assert served_rows[tie_speed]["average_speed_kmh"] == 38.3
    empty_road = ("ROAD_001", "2026-10-20T08:11:00Z")  # route vide en pleine congestion
    gap, resumed = ("ROAD_001", "2026-10-20T08:12:00Z"), ("ROAD_001", "2026-10-20T08:13:00Z")
    assert empty_road not in served_rows
    assert served_rows[gap]["congestion_state"] == "UNKNOWN"  # trou de données
    assert served_rows[resumed]["congestion_state"] == "CONGESTED"  # reclassé à l'entrée
    suspect, partial = ("ROAD_003", "2026-10-20T08:15:00Z"), ("ROAD_003", "2026-10-20T08:05:00Z")
    assert served_rows[suspect]["sample_count"] == 5  # la mesure suspecte est exclue
    assert served_rows[partial]["sample_count"] == 6  # les partielles sont retenues


COUNT_FACTS = "SELECT count(*), sum(vehicle_count), sum(sample_count) FROM dwh.fact_traffic_window"


def test_l_ecriture_est_idempotente_rejouer_les_indicateurs_ne_change_rien(chain):
    engine, _, indicators, _ = chain
    before = scalar_row(engine, COUNT_FACTS)

    writer = WarehouseWriter(url_of(engine))
    pipeline = Pipeline(
        writer,
        Recommender(writer.load_plan_reference()),
        FakePublisher(),
        FakeArchive(),
        FakeStats(),
    )
    for offset, event in enumerate(indicators):
        pipeline.handle(json.dumps(event).encode(), event["subject"].encode(), 0, offset)
    pipeline.checkpoint()
    writer.close()

    assert scalar_row(engine, COUNT_FACTS) == before
    runs = scalar_row(engine, "SELECT count(*) FROM dwh.dim_run WHERE run_id = :r", r=RUN)
    assert runs == (1,)


def test_l_execution_est_enregistree_avec_sa_provenance_complete(chain):
    engine, *_ = chain
    sql = "SELECT source_type, scenario_id, seed FROM dwh.dim_run WHERE run_id = :r"

    assert scalar_row(engine, sql, r=RUN) == ("SIMULATED", "heure-de-pointe", 42)


def test_les_recommandations_publiees_suivent_les_etats_servis(chain, api):
    _, _, _, recommendations = chain
    served_rows = served(api, 60)

    assert recommendations, "la congestion du jeu de test doit produire des recommandations"
    for event in recommendations:
        data = event["data"]
        start = data["inputs"]["window_start"]
        segments = {i.split(":")[1] for i in data["inputs"]["indicator_ids"]}
        states = {served_rows[(s, start)]["congestion_state"] for s in segments}
        assert states & {"SLOW", "CONGESTED"}
        assert "UNKNOWN" not in states
        assert data["cycle_s"] == sum(p["duration_s"] for p in data["phases"])


def test_kpi_01_part_du_temps_congestionne_suit_les_etats_du_recalcul(chain):
    """Un indicateur décisionnel (DAT-07) lu sur les faits écrits = celui des états recalculés."""
    engine, *_ = chain
    published = {
        (row["road_segment_id"], row["window_start"]): row
        for row in reference_rows(engine)
        if row["window_size_s"] == 60 and row["closed"]
        and not (row["congestion_state"] in ("SLOW", "CONGESTED") and row["speed_ratio"] is None)
    }  # fmt: skip
    expected: dict[str, list[int]] = {}
    for (segment, _), row in published.items():
        congested, observed, unknown = expected.setdefault(segment, [0, 0, 0])
        state = row["congestion_state"]
        expected[segment] = [
            congested + 60 * (state == "CONGESTED"),
            observed + 60 * (state != "UNKNOWN"),
            unknown + 60 * (state == "UNKNOWN"),
        ]

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT road_segment_id, congestionne_s, observe_s, inconnu_s "
                "FROM dwh.kpi_part_temps_congestionne WHERE run_id = :run AND window_size_s = 60"
            ),
            {"run": RUN},
        ).all()
    assert {
        r.road_segment_id: [r.congestionne_s, r.observe_s, r.inconnu_s] for r in rows
    } == expected
    assert any(values[0] > 0 for values in expected.values())  # la congestion du jeu est comptée
