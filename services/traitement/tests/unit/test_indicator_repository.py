"""Requêtes de lecture des indicateurs (BE-04), sans base : le SQL est lu, pas exécuté.

L'exécution réelle, et l'accord avec le dépôt en mémoire, sont vérifiés par
`tests/integration/test_indicators_postgres.py`.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.db import session as session_module
from app.repositories.indicators import (
    DEFAULT_WINDOW_SIZE_S,
    V_INDICATOR,
    IndicatorFilters,
    IndicatorRow,
    SqlIndicatorRepository,
)

DEBUT = datetime(2026, 10, 20, 8, 20, tzinfo=UTC)
FIN = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def sql_of(statement) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def listed(filters: IndicatorFilters, *, limit=10, after=None) -> str:
    session = MagicMock()
    session.execute.return_value = iter([])
    assert SqlIndicatorRepository(session).list_page(filters, limit=limit, after=after) == []
    return sql_of(session.execute.call_args.args[0])


def test_the_view_is_read_with_the_columns_of_the_row_dataclass():
    colonnes = {c.name for c in V_INDICATOR.columns}
    assert colonnes == set(IndicatorRow.__dataclass_fields__)
    assert str(V_INDICATOR.fullname) == "dwh.v_indicator"


def test_the_default_list_keeps_one_minute_windows_and_is_sorted_and_limited():
    sql = listed(IndicatorFilters())
    assert f"dwh.v_indicator.window_size_s = {DEFAULT_WINDOW_SIZE_S}" in sql
    assert (
        'ORDER BY dwh.v_indicator.window_start DESC, dwh.v_indicator.road_segment_id COLLATE "C", '
        'dwh.v_indicator.run_id COLLATE "C"' in sql
    )
    assert sql.rstrip().endswith("LIMIT 10")
    assert sql.count("WHERE") == 1 and "dwh.v_indicator.run_id =" not in sql


def test_every_filter_becomes_one_condition_on_the_right_column():
    sql = listed(
        IndicatorFilters(
            window_size_s=300,
            intersection_id="INT_01",
            road_segment_id="ROAD_001",
            start=DEBUT,
            end=FIN,
            congestion_state="CONGESTED",
            run_id="run-a",
            source_type="SIMULATED",
        )
    )
    for condition in (
        "window_size_s = 300",
        "intersection_id = 'INT_01'",
        "road_segment_id = 'ROAD_001'",
        "window_start >= '2026-10-20 08:20:00+00:00'",
        "window_start < '2026-10-20 09:00:00+00:00'",
        "congestion_state = 'CONGESTED'",
        "run_id = 'run-a'",
        "source_type = 'SIMULATED'",
    ):
        assert f"dwh.v_indicator.{condition}" in sql, condition


def test_a_filter_value_is_bound_never_pasted_into_the_query():
    session = MagicMock()
    session.execute.return_value = iter([])
    SqlIndicatorRepository(session).list_page(
        IndicatorFilters(road_segment_id="x' OR '1'='1"), limit=1, after=None
    )
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "x' OR" not in str(compiled)
    assert "x' OR '1'='1" in compiled.params.values()


def test_the_period_is_half_open_from_included_to_excluded():
    sql = listed(IndicatorFilters(start=DEBUT, end=FIN))
    assert "window_start >=" in sql and "window_start <" in sql
    assert "window_start <=" not in sql and "window_start >" not in sql.replace(
        "window_start >=", ""
    )


def test_a_cursor_resumes_strictly_after_the_last_row_seen():
    sql = listed(IndicatorFilters(), after=(DEBUT, "ROAD_003", "run-a"))
    assert "dwh.v_indicator.window_start < '2026-10-20 08:20:00+00:00'" in sql
    assert "dwh.v_indicator.window_start = '2026-10-20 08:20:00+00:00'" in sql
    assert (
        '(dwh.v_indicator.road_segment_id COLLATE "C", dwh.v_indicator.run_id COLLATE "C") > '
        "('ROAD_003', 'run-a')" in sql
    )


def test_the_row_mapping_gives_every_field():
    valeurs = {nom: None for nom in IndicatorRow.__dataclass_fields__}
    valeurs |= {"indicator_id": "r:ROAD_001:60:0", "window_start": DEBUT}
    session = MagicMock()
    session.execute.return_value = iter([MagicMock(_mapping=valeurs)])
    lignes = SqlIndicatorRepository(session).list_page(IndicatorFilters(), limit=1, after=None)
    assert lignes == [IndicatorRow(**valeurs)]


def test_get_looks_up_the_four_parts_of_the_key():
    session = MagicMock()
    session.execute.return_value = iter([])
    resultat = SqlIndicatorRepository(session).get(
        run_id="r", road_segment_id="ROAD_001", window_size_s=60, window_start=DEBUT
    )
    assert resultat is None
    sql = sql_of(session.execute.call_args.args[0])
    for condition in ("run_id = 'r'", "road_segment_id = 'ROAD_001'", "window_size_s = 60"):
        assert f"dwh.v_indicator.{condition}" in sql
    assert "window_start = '2026-10-20 08:20:00+00:00'" in sql


def latest(**arguments) -> str:
    session = MagicMock()
    session.execute.return_value = iter([])
    assert SqlIndicatorRepository(session).latest(**arguments) == []
    return sql_of(session.execute.call_args.args[0])


def test_latest_takes_one_minute_window_per_segment_the_most_recent():
    sql = latest(intersection_id=None, run_id="run-a")
    assert 'SELECT DISTINCT ON (dwh.v_indicator.road_segment_id COLLATE "C")' in sql
    assert "dwh.v_indicator.window_size_s = 60" in sql
    assert "dwh.v_indicator.run_id = 'run-a'" in sql
    assert (
        'ORDER BY dwh.v_indicator.road_segment_id COLLATE "C", dwh.v_indicator.window_start DESC'
        in sql
    )


def test_latest_without_a_run_reads_the_run_of_the_most_recent_minute_window():
    sql = latest(intersection_id="INT_02", run_id=None)
    assert "dwh.v_indicator.run_id = (SELECT dwh.v_indicator.run_id" in sql
    assert "ORDER BY dwh.v_indicator.window_start DESC" in sql
    assert "LIMIT 1" in sql
    assert "dwh.v_indicator.intersection_id = 'INT_02'" in sql


def test_nothing_in_the_module_writes():
    import inspect
    import re

    from app.repositories import indicators

    code = re.sub(r'""".*?"""', "", inspect.getsource(indicators), flags=re.S).lower()
    for interdit in (
        "insert(",
        "update(",
        "delete(",
        "commit(",
        "session.add",
        "flush(",
        "truncate",
    ):
        assert interdit not in code, interdit


def test_the_warehouse_session_is_opened_read_only(monkeypatch):
    appels = []

    def faux_moteur(url, **options):
        appels.append((url, options))
        return MagicMock()

    monkeypatch.setenv("POSTGRES_URL", "postgresql+psycopg://svc_traitement:secret@h/d")
    from app.core.config import get_settings

    get_settings.cache_clear()
    session_module.get_warehouse_session_factory.cache_clear()
    monkeypatch.setattr(session_module, "create_engine", faux_moteur)
    try:
        session_module.get_warehouse_session_factory()
    finally:
        session_module.get_warehouse_session_factory.cache_clear()
        get_settings.cache_clear()
    url, options = appels[0]
    assert url.startswith("postgresql+psycopg://svc_traitement:")
    assert options["connect_args"] == {"options": "-c default_transaction_read_only=on"}
    assert options["pool_pre_ping"] is True


def test_the_repository_dependency_yields_a_sql_repository(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", "sqlite://")
    from app.core.config import get_settings

    get_settings.cache_clear()
    session_module.get_warehouse_session_factory.cache_clear()
    monkeypatch.setattr(session_module, "READ_ONLY", {})
    try:
        generateur = session_module.get_indicator_repository()
        assert isinstance(next(generateur), SqlIndicatorRepository)
    finally:
        session_module.get_warehouse_session_factory.cache_clear()
        get_settings.cache_clear()
