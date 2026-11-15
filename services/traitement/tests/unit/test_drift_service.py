"""Surveillance de la dérive sur un entrepôt (IA-06) : lecture, comparaison, annonce de l'alerte."""

import json
import logging
from datetime import UTC, datetime, timedelta

from app.drift import alert
from app.drift.monitor import Status, Thresholds
from app.drift.service import DriftMonitor, compare
from app.drift.source import PAGE_SIZE, latest_run_id, read_samples
from tests.drift_data import SEGMENTS, calm, moderately_slower, rush
from tests.fakes import START, FakeIndicatorRepository, make_row

THRESHOLDS = Thresholds()


def warehouse(*runs) -> FakeIndicatorRepository:
    return FakeIndicatorRepository([row for run in runs for row in run])


def do_compare(indicators, **kwargs):
    return compare(
        indicators,
        reference_run_id=kwargs.pop("reference_run_id", "run-calme"),
        thresholds=THRESHOLDS,
        max_rows=kwargs.pop("max_rows", 20000),
        **kwargs,
    )


# --- Lecture -----------------------------------------------------------------------------------


def test_the_current_run_is_the_one_of_the_most_recent_window():
    old = calm("run-calme")
    new = [make_row(run_id="run-recent", window_start=START + timedelta(days=1))]
    assert latest_run_id(warehouse(old, new)) == "run-recent"
    assert latest_run_id(FakeIndicatorRepository()) is None


def test_every_page_of_a_run_is_read_and_only_that_run():
    rows = calm("run-calme") + rush("run-pointe")
    assert len(calm()) > PAGE_SIZE, "le test doit traverser plusieurs pages"
    samples = read_samples(warehouse(rows), "run-calme", max_rows=100000)
    assert len(samples["speed_ratio"]) == len(calm())
    assert max(samples["speed_ratio"]) > 0.8 and min(samples["speed_ratio"]) > 0.5, (
        "rien de la pointe"
    )


def test_the_row_cap_keeps_the_most_recent_windows():
    samples = read_samples(warehouse(calm()), "run-calme", max_rows=40)
    assert len(samples["speed_ratio"]) == 40


def test_empty_values_are_left_out_and_five_minute_windows_are_ignored():
    rows = [
        make_row(run_id="r", speed_ratio=None, window_start=START),
        make_row(run_id="r", speed_ratio=0.7, window_start=START + timedelta(minutes=1)),
        make_row(run_id="r", window_size_s=300, speed_ratio=0.1, window_start=START),
    ]
    samples = read_samples(FakeIndicatorRepository(rows), "r", max_rows=100)
    assert samples["speed_ratio"] == [0.7]


# --- Comparaison -------------------------------------------------------------------------------


def test_a_shifted_current_run_is_an_alert_against_the_reference_run():
    report = do_compare(warehouse(calm("run-calme"), rush("run-pointe")))
    assert (report.reference_run_id, report.current_run_id) == ("run-calme", "run-pointe")
    assert report.status is Status.ALERT


def test_the_reference_run_against_itself_is_stable():
    report = do_compare(warehouse(calm("run-calme")))
    assert (report.current_run_id, report.status) == ("run-calme", Status.OK)


def test_a_moderate_shift_only_warns():
    assert do_compare(warehouse(calm("run-calme"), moderately_slower())).status is Status.WARN


def test_an_explicit_current_run_is_compared_even_if_it_is_not_the_latest():
    indicators = warehouse(calm("run-calme"), rush("run-pointe"))
    report = do_compare(indicators, current_run_id="run-calme")
    assert report.current_run_id == "run-calme"
    assert report.status is Status.OK


def test_an_empty_warehouse_has_no_data_and_no_alert():
    report = do_compare(FakeIndicatorRepository())
    assert (report.status, report.is_alert) == (Status.NO_DATA, False)


def test_without_a_reference_run_nothing_can_be_judged():
    report = do_compare(warehouse(calm("run-calme")), reference_run_id=None)
    assert (report.status, report.is_alert) == (Status.NO_REFERENCE, False)
    assert "DRIFT_REFERENCE_RUN_ID" in (report.reason or "")


def test_an_unknown_reference_run_has_too_few_values_and_gives_no_alert():
    report = do_compare(warehouse(rush("run-pointe")), reference_run_id="n-existe-pas")
    assert (report.status, report.is_alert) == (Status.INSUFFICIENT_DATA, False)


def test_the_segments_of_the_fixtures_are_what_the_comparison_reads():
    assert len(SEGMENTS) == 5


# --- Moniteur : cache et annonce ----------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class CountingRepository(FakeIndicatorRepository):
    def __init__(self, rows) -> None:
        super().__init__(rows)
        self.reads = 0

    def latest(self, **kwargs):
        self.reads += 1
        return super().latest(**kwargs)


def monitor(clock, reference="run-calme", cache_s=30.0) -> DriftMonitor:
    return DriftMonitor(
        reference_run_id=reference,
        thresholds=THRESHOLDS,
        max_rows=20000,
        cache_s=cache_s,
        clock=clock,
    )


def alerts(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == alert.ALERT_MESSAGE]


def test_the_warehouse_is_read_again_only_after_the_cache_delay():
    clock, indicators = Clock(), CountingRepository(calm("run-calme"))
    m = monitor(clock)
    first = m.report(indicators)
    assert m.report(indicators) is first and indicators.reads == 1
    clock.now += 31
    assert m.report(indicators) is not first and indicators.reads == 2


def test_the_alert_is_logged_once_per_drift_not_at_every_reading(caplog):
    clock, indicators = Clock(), warehouse(calm("run-calme"), rush("run-pointe"))
    m = monitor(clock, cache_s=0)
    with caplog.at_level(logging.INFO, logger="app.drift"):
        for _ in range(4):
            assert m.report(indicators).status is Status.ALERT
            clock.now += 1
    (record,) = alerts(caplog)
    assert record.levelno == logging.WARNING
    assert record.fields["event"] == "input_drift"
    assert record.fields["reference_run_id"] == "run-calme"
    assert record.fields["current_run_id"] == "run-pointe"
    assert set(record.fields["features"]) == {"speed_ratio", "flow_veh_per_min", "occupancy_rate"}
    assert record.fields["alert_threshold"] == 0.25


def test_the_alert_line_is_one_json_object_with_the_drifting_variables(caplog, capsys):
    from app.core.logs import JsonFormatter

    indicators = warehouse(calm("run-calme"), rush("run-pointe"))
    with caplog.at_level(logging.INFO, logger="app.drift"):
        monitor(Clock()).report(indicators)
    (record,) = alerts(caplog)
    line = json.loads(JsonFormatter("traitement").format(record))
    assert (line["level"], line["message"], line["service"]) == (
        "WARNING",
        alert.ALERT_MESSAGE,
        "traitement",
    )
    assert line["status"] == "ALERT" and line["features"]["speed_ratio"] > 0.25


def test_a_new_run_that_drifts_is_announced_again_and_the_return_to_normal_too(caplog):
    clock, indicators = Clock(), warehouse(calm("run-calme"), rush("run-pointe"))
    m = monitor(clock, cache_s=0)
    with caplog.at_level(logging.INFO, logger="app.drift"):
        m.report(indicators)
        later = START + timedelta(days=2)
        indicators.rows += [
            make_row(
                run_id="run-calme",
                window_start=later,
                speed_ratio=0.9,
                flow_veh_per_min=8.0,
                occupancy_rate=0.15,
            )
        ]
        clock.now += 1
        m.report(indicators)  # la fenêtre la plus récente est maintenant celle du run de référence
    messages = [r.getMessage() for r in caplog.records if r.name == "app.drift"]
    assert messages == [alert.ALERT_MESSAGE, alert.CLEARED_MESSAGE]


def test_a_missing_verdict_neither_raises_nor_clears_an_alert(caplog):
    clock, indicators = Clock(), warehouse(calm("run-calme"), rush("run-pointe"))
    m = monitor(clock, cache_s=0)
    with caplog.at_level(logging.INFO, logger="app.drift"):
        m.report(indicators)
        indicators.rows.clear()
        clock.now += 1
        assert m.report(indicators).status is Status.NO_DATA
    assert [r.getMessage() for r in caplog.records if r.name == "app.drift"] == [
        alert.ALERT_MESSAGE
    ]


def test_a_stable_run_never_logs_an_alert(caplog):
    with caplog.at_level(logging.DEBUG, logger="app.drift"):
        monitor(Clock()).report(warehouse(calm("run-calme")))
    assert [r for r in caplog.records if r.name == "app.drift"] == []


def test_the_time_of_the_report_is_in_utc():
    report = do_compare(warehouse(calm("run-calme")))
    assert report.checked_at.tzinfo is not None
    assert abs(datetime.now(UTC) - report.checked_at) < timedelta(minutes=1)
