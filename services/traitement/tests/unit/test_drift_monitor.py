"""Décision de dérive (IA-06, EXG-IA-05) : la dérive simulée alerte, une série stable non."""

from datetime import UTC, datetime

import pytest

from app.drift.monitor import FEATURES, Status, Thresholds, evaluate
from tests.drift_data import calm, moderately_slower, rush

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def samples(rows) -> dict[str, list[float]]:
    return {name: [getattr(r, name) for r in rows] for name in FEATURES}


def check(reference, current, **kwargs):
    return evaluate(
        samples(reference),
        samples(current),
        checked_at=NOW,
        reference_run_id="ref",
        current_run_id="cur",
        **kwargs,
    )


def test_a_stable_run_is_ok_and_every_variable_is_below_the_warning_threshold():
    report = check(calm("a", seed=1), calm("b", seed=2))
    assert report.status is Status.OK
    assert not report.is_alert
    assert [f.feature for f in report.features] == list(FEATURES)
    assert all(f.psi < Thresholds().warn for f in report.features)


def test_simulated_drift_triggers_the_alert_on_every_shifted_variable():
    """Vitesses effondrées, débit et occupation en hausse : les trois variables sortent."""
    report = check(calm(), rush())
    assert report.status is Status.ALERT
    assert report.is_alert
    assert {f.feature for f in report.drifting} == set(FEATURES)
    assert report.drifting[0].psi >= report.drifting[-1].psi, "la plus décalée d'abord"
    speed = next(f for f in report.features if f.feature == "speed_ratio")
    assert speed.psi > 0.25
    assert speed.reference_mean > 0.9 > 0.5 > speed.current_mean


def test_a_small_shift_is_a_warning_not_an_alert():
    report = check(calm(), moderately_slower())
    assert report.status is Status.WARN
    assert not report.is_alert
    speed = next(f for f in report.features if f.feature == "speed_ratio")
    assert Thresholds().warn <= speed.psi < Thresholds().alert


def test_thresholds_decide_the_verdict():
    reference, current = calm(), moderately_slower()
    strict = check(reference, current, thresholds=Thresholds(warn=0.01, alert=0.05))
    lax = check(reference, current, thresholds=Thresholds(warn=5.0, alert=10.0))
    assert strict.status is Status.ALERT
    assert lax.status is Status.OK


def test_too_few_values_give_no_verdict_instead_of_a_false_alert():
    report = check(calm(minutes=3), rush(minutes=3))  # 15 fenêtres par exécution
    assert report.status is Status.INSUFFICIENT_DATA
    assert not report.is_alert
    assert report.features == []
    assert "valeurs" in (report.reason or "")


def test_the_overall_status_is_the_worst_variable():
    reference, current = calm(), calm("autre", seed=5)
    drifted = [r.__class__(**{**r.__dict__, "occupancy_rate": 0.95}) for r in current]
    report = check(reference, drifted)
    assert report.status is Status.ALERT
    assert [f.feature for f in report.drifting] == ["occupancy_rate"]


@pytest.mark.parametrize(
    "kwargs",
    [{"warn": 0.0}, {"warn": 0.3, "alert": 0.2}, {"warn": 0.1, "alert": 0.1}, {"min_samples": 5}],
)
def test_incoherent_thresholds_are_refused(kwargs):
    with pytest.raises(ValueError):
        Thresholds(**kwargs)
