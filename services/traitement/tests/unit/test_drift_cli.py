"""Script de dérive `python -m app.drift check` (IA-06) : sortie, journal et code de sortie."""

import json
import logging
from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.drift import __main__ as cli
from app.drift.alert import ALERT_MESSAGE
from tests.drift_data import calm, moderately_slower, rush
from tests.fakes import FakeIndicatorRepository


@pytest.fixture
def warehouse(monkeypatch):
    """L'entrepôt en mémoire à la place de la base ; la configuration vient de l'environnement."""
    repository = FakeIndicatorRepository()

    @contextmanager
    def session():
        yield object()

    monkeypatch.setattr(cli, "get_warehouse_session_factory", lambda: session)
    monkeypatch.setattr(cli, "SqlIndicatorRepository", lambda _: repository)
    monkeypatch.setattr(cli, "configure_logging", lambda *a, **k: None)
    monkeypatch.delenv("DRIFT_REFERENCE_RUN_ID", raising=False)
    get_settings.cache_clear()
    yield repository
    get_settings.cache_clear()


def run(argv, capsys):
    code = cli.main(argv)
    return code, capsys.readouterr().out


def test_a_simulated_drift_exits_with_one_prints_the_variables_and_logs_the_alert(
    warehouse, capsys, caplog
):
    warehouse.rows += calm("run-calme") + rush("run-pointe")
    with caplog.at_level(logging.INFO, logger="app.drift"):
        code, out = run(["check", "--reference-run", "run-calme"], capsys)
    assert code == cli.EXIT_DRIFT == 1
    assert "Dérive des entrées : ALERT" in out
    assert "speed_ratio" in out and "run-calme" in out and "run-pointe" in out
    (record,) = [r for r in caplog.records if r.getMessage() == ALERT_MESSAGE]
    assert record.fields["current_run_id"] == "run-pointe"


def test_a_stable_run_exits_with_zero_and_logs_nothing(warehouse, capsys, caplog):
    warehouse.rows += calm("run-calme")
    with caplog.at_level(logging.INFO, logger="app.drift"):
        code, out = run(["check", "--reference-run", "run-calme"], capsys)
    assert code == 0
    assert "Dérive des entrées : OK" in out
    assert [r for r in caplog.records if r.name == "app.drift"] == []


def test_a_moderate_shift_is_not_a_failure(warehouse, capsys):
    warehouse.rows += calm("run-calme") + moderately_slower()
    code, out = run(["check", "--reference-run", "run-calme"], capsys)
    assert (code, "WARN" in out) == (0, True)


def test_the_reference_run_can_come_from_the_environment(warehouse, capsys, monkeypatch):
    warehouse.rows += calm("run-calme") + rush("run-pointe")
    monkeypatch.setenv("DRIFT_REFERENCE_RUN_ID", "run-calme")
    get_settings.cache_clear()
    assert run(["check"], capsys)[0] == 1


def test_the_json_report_has_the_status_the_runs_and_one_psi_per_variable(warehouse, capsys):
    warehouse.rows += calm("run-calme") + rush("run-pointe")
    code, out = run(["check", "--reference-run", "run-calme", "--json"], capsys)
    report, _ = json.JSONDecoder().raw_decode(out)  # des lignes de journal peuvent suivre
    assert code == 1 and report["status"] == "ALERT"
    assert (report["reference_run_id"], report["current_run_id"]) == ("run-calme", "run-pointe")
    assert {f["feature"] for f in report["features"]} == {
        "speed_ratio",
        "flow_veh_per_min",
        "occupancy_rate",
    }
    assert all(f["psi"] > 0.25 for f in report["features"])
    assert report["thresholds"] == {"warn": 0.1, "alert": 0.25, "min_samples": 100}


@pytest.mark.parametrize(
    ("rows", "argv", "status"),
    [
        ([], ["check", "--reference-run", "run-calme"], "NO_DATA"),
        (calm("run-calme"), ["check"], "NO_REFERENCE"),
        (calm("run-calme"), ["check", "--reference-run", "inconnue"], "INSUFFICIENT_DATA"),
    ],
)
def test_a_comparison_that_cannot_be_made_exits_with_two(warehouse, capsys, rows, argv, status):
    warehouse.rows += rows
    code, out = run(argv, capsys)
    assert code == cli.EXIT_UNAVAILABLE == 2
    assert status in out


def test_an_unconfigured_warehouse_exits_with_two_and_says_why(monkeypatch, capsys):
    from app.db.session import DatabaseNotConfigured

    def missing():
        raise DatabaseNotConfigured("POSTGRES_URL")

    monkeypatch.setattr(cli, "get_warehouse_session_factory", missing)
    monkeypatch.setattr(cli, "configure_logging", lambda *a, **k: None)
    assert cli.main(["check", "--reference-run", "x"]) == 2
    assert "POSTGRES_URL" in capsys.readouterr().err


def test_the_thresholds_must_be_ordered_at_startup():
    with pytest.raises(ValidationError):
        Settings(drift_warn_psi=0.3, drift_alert_psi=0.2)
    assert Settings().drift_reference_run_id is None
