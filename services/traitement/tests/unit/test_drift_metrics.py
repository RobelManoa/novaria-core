"""Format Prometheus des indicateurs de dérive (IA-06)."""

import re
from datetime import UTC, datetime

from app.drift import metrics
from app.drift.monitor import FEATURES, Status, Thresholds, evaluate
from tests.drift_data import calm, rush

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
SAMPLE = re.compile(r"^([a-z_]+)(\{[^}]*\})? (-?[0-9.]+(?:e[+-]?[0-9]+)?)$")


def samples(rows):
    return {name: [getattr(r, name) for r in rows] for name in FEATURES}


def report(current, **kwargs):
    return evaluate(
        samples(calm()),
        samples(current),
        checked_at=NOW,
        reference_run_id=kwargs.get("reference", "run-calme"),
        current_run_id="run-pointe",
        thresholds=Thresholds(),
    )


def parse(text: str) -> dict[str, float]:
    """Clé = nom et étiquettes ; échoue si une ligne n'est ni un commentaire ni un échantillon."""
    values = {}
    for line in text.splitlines():
        if line.startswith("#"):
            assert re.match(r"^# (HELP|TYPE) novaria_[a-z_]+ .+", line), line
            continue
        found = SAMPLE.match(line)
        assert found, f"ligne invalide : {line!r}"
        values[found.group(1) + (found.group(2) or "")] = float(found.group(3))
    return values


def test_a_drift_exposes_the_alert_indicator_at_one_and_a_psi_per_variable():
    values = parse(metrics.render(report(rush())))
    assert values["novaria_input_drift_alert"] == 1
    assert values["novaria_input_drift_check_ok"] == 1
    assert values['novaria_input_drift_status{status="ALERT"}'] == 1
    for feature in FEATURES:
        assert values[f'novaria_input_drift_psi{{feature="{feature}"}}'] > 0.25


def test_a_stable_run_exposes_the_alert_indicator_at_zero():
    values = parse(metrics.render(report(calm("autre", seed=2))))
    assert values["novaria_input_drift_alert"] == 0
    assert values['novaria_input_drift_status{status="OK"}'] == 1
    assert all(
        values[f'novaria_input_drift_psi{{feature="{feature}"}}'] < 0.10 for feature in FEATURES
    )


def test_exactly_one_status_is_set():
    for current in (rush(), calm("autre", seed=2)):
        values = parse(metrics.render(report(current)))
        statuses = {k: v for k, v in values.items() if k.startswith("novaria_input_drift_status")}
        assert sorted(statuses.values()) == [0] * (len(Status) - 1) + [1]


def test_without_a_verdict_there_is_no_psi_no_alert_and_the_check_is_not_ok():
    absent = evaluate(
        {}, {}, checked_at=NOW, reference_run_id=None, current_run_id=None, thresholds=Thresholds()
    )
    values = parse(metrics.render(absent))
    assert values["novaria_input_drift_alert"] == 0
    assert values["novaria_input_drift_check_ok"] == 0
    assert not [k for k in values if k.startswith("novaria_input_drift_psi")]


def test_thresholds_and_time_are_exposed():
    values = parse(metrics.render(report(rush())))
    assert values['novaria_input_drift_threshold{level="warn"}'] == 0.1
    assert values['novaria_input_drift_threshold{level="alert"}'] == 0.25
    assert values["novaria_input_drift_checked_timestamp_seconds"] == NOW.timestamp()


def test_run_identifiers_are_escaped_in_labels():
    text = metrics.render(report(rush(), reference='a"b\\c\nd'))
    assert 'reference_run_id="a\\"b\\\\c\\nd"' in text
    parse(text)


def test_the_text_ends_with_a_newline_and_declares_each_family_once():
    text = metrics.render(report(rush()))
    assert text.endswith("\n")
    families = re.findall(r"^# TYPE (\S+) gauge$", text, re.M)
    assert len(families) == len(set(families)) == 7
