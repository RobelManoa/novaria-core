"""Le dépôt SQL des vitesses (IA-16), sans base : session factice, SQL lu, lignes converties.

L'exécution réelle contre PostgreSQL est vérifiée par la pile locale (`dev.py etl-vitesses`, puis
l'API).
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.core.errors import ProblemError
from app.db import session as session_module
from app.repositories.speed import (
    Coverage,
    SpeedNetwork,
    SpeedReading,
    SqlSpeedRepository,
)

A = datetime(2012, 6, 20, 8, 0, tzinfo=UTC)
B = datetime(2012, 6, 20, 8, 5, tzinfo=UTC)
RESEAU = ("metr-la", "METR-LA", "essai", "REAL_HISTORICAL", 300, "mph")


def depot(*resultats):
    session = MagicMock()
    session.execute.side_effect = list(resultats)
    return SqlSpeedRepository(session), session


def sql(session, appel=0) -> str:
    return str(session.execute.call_args_list[appel].args[0])


def test_the_networks_are_listed_in_binary_order():
    repo, session = depot(iter([RESEAU]))
    assert repo.list_networks() == [SpeedNetwork(*RESEAU)]
    assert 'ORDER BY network_id COLLATE "C"' in sql(session)


def test_one_network_is_read_by_its_identifier_or_is_absent():
    repo, session = depot(MagicMock(first=lambda: RESEAU))
    assert repo.get_network("metr-la") == SpeedNetwork(*RESEAU)
    assert session.execute.call_args.args[1] == {"n": "metr-la"}
    repo, _ = depot(MagicMock(first=lambda: None))
    assert repo.get_network("inconnu") is None


def test_the_sensors_come_back_in_rank_order():
    repo, session = depot(iter([("S1",), ("S2",)]))
    assert repo.sensors("metr-la") == ["S1", "S2"]
    assert "ORDER BY sensor_key" in sql(session)


def test_the_coverage_counts_distinct_steps_and_sensors():
    repo, _ = depot(MagicMock(one=lambda: (A, B, 2)), MagicMock(scalar_one=lambda: 207))
    assert repo.coverage("metr-la") == Coverage(A, B, 2, 207)
    vide, _ = depot(MagicMock(one=lambda: (None, None, None)), MagicMock(scalar_one=lambda: None))
    assert vide.coverage("x") == Coverage(None, None, 0, 0)


def test_the_last_instant_is_bounded_only_when_a_date_is_given():
    repo, session = depot(MagicMock(scalar_one=lambda: B))
    assert repo.last_before("metr-la", None) == B
    assert "observed_at <=" not in sql(session)
    assert session.execute.call_args.args[1] == {"n": "metr-la"}
    repo, session = depot(MagicMock(scalar_one=lambda: A))
    assert repo.last_before("metr-la", A) == A
    assert "observed_at <= :at" in sql(session)
    assert session.execute.call_args.args[1] == {"n": "metr-la", "at": A}


def test_the_readings_are_measured_speeds_named_by_sensor():
    repo, session = depot(iter([(A, "S1", 60.5), (B, "S2", "55")]))
    assert repo.readings("metr-la", A, B) == [
        SpeedReading(A, "S1", 60.5),
        SpeedReading(B, "S2", 55.0),
    ]
    requete = sql(session)
    assert "BETWEEN :a AND :b" in requete and "ORDER BY f.observed_at, s.sensor_key" in requete


def test_nothing_in_the_module_writes():
    import inspect
    import re

    from app.repositories import speed

    code = re.sub(r'""".*?"""', "", inspect.getsource(speed), flags=re.S).lower()
    for interdit in ("insert ", "update ", "delete ", "commit(", "session.add", "truncate"):
        assert interdit not in code, interdit


def test_the_repository_dependency_yields_a_sql_repository(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", "sqlite://")
    from app.core.config import get_settings

    get_settings.cache_clear()
    session_module.get_warehouse_session_factory.cache_clear()
    monkeypatch.setattr(session_module, "READ_ONLY", {})
    monkeypatch.setattr(session_module, "CONNECT", {})
    try:
        assert isinstance(next(session_module.get_speed_repository()), SqlSpeedRepository)
    finally:
        session_module.get_warehouse_session_factory.cache_clear()
        get_settings.cache_clear()


def test_without_a_warehouse_the_dependency_answers_503(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    session_module.get_warehouse_session_factory.cache_clear()
    try:
        with pytest.raises(ProblemError) as erreur:
            next(session_module.get_speed_repository())
    finally:
        session_module.get_warehouse_session_factory.cache_clear()
        get_settings.cache_clear()
    assert erreur.value.kind.status == 503
