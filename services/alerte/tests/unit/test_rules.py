"""Règles d'alerte : séries de fenêtres, seuils, idempotence (MS-11, ADR-028)."""

import dataclasses

import pytest

from app.domain.model import Kind, Open, Resolve, Rule, Severity
from app.domain.rules import (
    DEFAULTS,
    MAX_SERIES,
    RuleEngine,
    invalid_params,
    settings_of,
)
from app.schemas.events import IndicatorEvent
from app.services.ingestion import to_window
from tests.support import SEED_RULES, congested, indicator, silent

CONGESTION, ANOMALY, SENSOR = SEED_RULES


def window(event: dict):
    return to_window(IndicatorEvent.model_validate(event))


def decide(engine: RuleEngine, event: dict, rules=SEED_RULES):
    return engine.evaluate(window(event), list(rules))


def kinds(decisions):
    return [(type(d).__name__, d.rule.kind if isinstance(d, Open) else d.kind) for d in decisions]


# ----------------------------------------------------------------------------------- congestion
def test_a_congested_window_opens_a_congestion_alert():
    decisions = decide(RuleEngine(), congested(0), [CONGESTION])
    assert kinds(decisions) == [("Open", Kind.CONGESTION)]
    opened = decisions[0]
    assert opened.severity is Severity.WARNING
    assert opened.facts == {"congestion_state": "CONGESTED", "speed_ratio": 0.2}


def test_a_free_flow_window_resolves_the_congestion_alert():
    decisions = decide(RuleEngine(), indicator(0, "FREE_FLOW"))
    assert kinds(decisions) == [("Resolve", Kind.CONGESTION), ("Resolve", Kind.TRAFFIC_ANOMALY),
                                ("Resolve", Kind.SENSOR_FAULT)]  # fmt: skip


def test_a_slow_window_does_not_alert_nor_close_a_congestion_episode():
    """SLOW sous le seuil CONGESTED : l'épisode est ouvert, mais pas assez grave pour alerter."""
    decisions = decide(RuleEngine(), indicator(0, "SLOW", ratio=0.5))
    assert [k for k, kind in kinds(decisions) if kind is Kind.CONGESTION] == []


def test_the_trigger_state_is_configurable():
    early = dataclasses.replace(CONGESTION, params={"state": "SLOW", "min_windows": 1})
    decisions = decide(RuleEngine(), indicator(0, "SLOW", ratio=0.5), [early])
    assert kinds(decisions) == [("Open", Kind.CONGESTION)]


def test_min_windows_waits_for_consecutive_windows():
    rule = dataclasses.replace(CONGESTION, params={"state": "CONGESTED", "min_windows": 3})
    engine = RuleEngine()
    assert decide(engine, congested(0), [rule]) == []
    assert decide(engine, congested(1), [rule]) == []
    assert kinds(decide(engine, congested(2), [rule])) == [("Open", Kind.CONGESTION)]
    assert kinds(decide(engine, congested(3), [rule])) == [("Open", Kind.CONGESTION)]


def test_a_window_with_less_data_breaks_the_series_of_min_windows():
    rule = dataclasses.replace(CONGESTION, params={"state": "CONGESTED", "min_windows": 2})
    engine = RuleEngine()
    decide(engine, congested(0), [rule])
    decide(engine, silent(1), [rule])  # UNKNOWN : ni preuve, ni retour au fluide
    assert decide(engine, congested(2), [rule]) == []  # la série repart de 1


def test_unknown_neither_alerts_nor_resolves():
    assert decide(RuleEngine(), silent(0), [CONGESTION]) == []


def test_a_window_already_seen_is_ignored_redelivery_and_late_correction():
    engine = RuleEngine()
    assert decide(engine, congested(5), [CONGESTION]) != []
    assert decide(engine, congested(5), [CONGESTION]) == []  # même fenêtre : relivraison
    assert decide(engine, congested(4), [CONGESTION]) == []  # plus ancienne : déjà dépassée


def test_five_minute_windows_are_ignored_they_only_repeat_the_state():
    assert decide(RuleEngine(), congested(0, size=300)) == []


def test_disabled_rules_decide_nothing():
    off = dataclasses.replace(CONGESTION, enabled=False)
    assert decide(RuleEngine(), congested(0), [off]) == []


def test_series_are_kept_per_segment_and_per_run():
    rule = dataclasses.replace(CONGESTION, params={"state": "CONGESTED", "min_windows": 2})
    engine = RuleEngine()
    decide(engine, congested(0, segment="ROAD_001"), [rule])
    assert decide(engine, congested(1, segment="ROAD_002"), [rule]) == []
    assert decide(engine, congested(1, run="autre-run"), [rule]) == []
    assert kinds(decide(engine, congested(1, segment="ROAD_001"), [rule])) != []


def test_the_oldest_series_are_forgotten_beyond_the_limit(monkeypatch):
    monkeypatch.setattr("app.domain.rules.MAX_SERIES", 3)
    engine = RuleEngine()
    for index in range(5):
        decide(engine, congested(0, segment=f"ROAD_{index + 1:03d}"), [CONGESTION])
    assert len(engine._series) == 3
    assert MAX_SERIES == 10_000


# ------------------------------------------------------------------------------------- anomalie
def saturated(minute: int, **changes):
    return indicator(
        minute, "FREE_FLOW", ratio=0.9, occupancy=changes.pop("occupancy", 0.9), **changes
    )


def test_three_saturated_fluid_windows_open_a_traffic_anomaly():
    engine = RuleEngine()
    assert decide(engine, saturated(0), [ANOMALY]) == []
    assert decide(engine, saturated(1), [ANOMALY]) == []
    decisions = decide(engine, saturated(2), [ANOMALY])
    assert kinds(decisions) == [("Open", Kind.TRAFFIC_ANOMALY)]
    assert decisions[0].severity is Severity.INFO
    assert decisions[0].facts["occupancy_rate"] == 0.9


@pytest.mark.parametrize(
    ("occupancy", "queue", "expected"),
    [
        (0.8, None, True),  # borne : occupation égale au seuil
        (0.79, None, False),
        (None, 150.0, True),  # borne : file égale au seuil
        (None, 149.9, False),
        (0.5, 200.0, True),  # l'un ou l'autre suffit
        (None, None, False),
    ],
)
def test_saturation_thresholds_are_inclusive(occupancy, queue, expected):
    rule = dataclasses.replace(ANOMALY, params={"min_windows": 1})
    decisions = decide(
        RuleEngine(), indicator(0, "FREE_FLOW", occupancy=occupancy, queue=queue), [rule]
    )
    assert (kinds(decisions) == [("Open", Kind.TRAFFIC_ANOMALY)]) is expected


def test_a_slowing_segment_is_left_to_the_congestion_rule():
    """Une saturation avec un état SLOW ou CONGESTED n'ouvre pas d'anomalie : une seule alerte."""
    rule = dataclasses.replace(ANOMALY, params={"min_windows": 1})
    for state in ("SLOW", "CONGESTED"):
        decisions = decide(RuleEngine(), indicator(0, state, ratio=0.3, occupancy=0.95), [rule])
        assert all(isinstance(d, Resolve) for d in decisions)  # l'anomalie est terminée


def test_the_anomaly_series_is_broken_by_an_unsaturated_window():
    engine = RuleEngine()
    decide(engine, saturated(0), [ANOMALY])
    decide(engine, saturated(1), [ANOMALY])
    decisions = decide(engine, indicator(2, "FREE_FLOW", occupancy=0.3), [ANOMALY])
    assert kinds(decisions) == [("Resolve", Kind.TRAFFIC_ANOMALY)]
    assert decide(engine, saturated(3), [ANOMALY]) == []  # il faut de nouveau trois fenêtres


def test_an_empty_or_unknown_window_proves_nothing_about_saturation():
    engine = RuleEngine()
    decide(engine, saturated(0), [ANOMALY])
    assert decide(engine, silent(1), [ANOMALY]) == []
    decide(engine, saturated(2), [ANOMALY])
    assert decide(engine, saturated(3), [ANOMALY]) == []  # la série a été interrompue


# ----------------------------------------------------------------------------------- capteur muet
def test_a_silent_window_opens_a_sensor_fault_not_a_congestion():
    decisions = decide(RuleEngine(), silent(0))
    assert [k for k in kinds(decisions) if k[0] == "Open"] == [("Open", Kind.SENSOR_FAULT)]
    assert decisions[-1].facts == {"silent_s": 60, "silence_s": 60}


def test_a_longer_silence_needs_several_empty_windows():
    rule = dataclasses.replace(SENSOR, params={"silence_s": 180})
    engine = RuleEngine()
    assert decide(engine, silent(0), [rule]) == []
    assert decide(engine, silent(1), [rule]) == []
    assert kinds(decide(engine, silent(2), [rule])) == [("Open", Kind.SENSOR_FAULT)]


def test_a_window_with_data_resolves_the_sensor_fault_and_restarts_the_silence():
    rule = dataclasses.replace(SENSOR, params={"silence_s": 120})
    engine = RuleEngine()
    decide(engine, silent(0), [rule])
    decisions = decide(engine, indicator(1, "FREE_FLOW"), [rule])
    assert kinds(decisions) == [("Resolve", Kind.SENSOR_FAULT)]
    assert decide(engine, silent(2), [rule]) == []  # le silence repart de zéro


# --------------------------------------------------------------------------------- paramètres
def test_missing_parameters_take_the_starting_values():
    assert settings_of(dataclasses.replace(CONGESTION, params={})) == DEFAULTS[Kind.CONGESTION]
    assert settings_of(dataclasses.replace(ANOMALY, params={"min_windows": 5}))["min_windows"] == 5
    assert settings_of(ANOMALY)["occupancy_min"] == 0.8


@pytest.mark.parametrize(
    ("kind", "params", "bad"),
    [
        (Kind.CONGESTION, {"state": "FREE_FLOW"}, ["state"]),
        (Kind.CONGESTION, {"min_windows": 0}, ["min_windows"]),
        (Kind.CONGESTION, {"min_windows": 61}, ["min_windows"]),
        (Kind.CONGESTION, {"min_windows": True}, ["min_windows"]),
        (Kind.CONGESTION, {"min_windows": 2.5}, ["min_windows"]),
        (Kind.CONGESTION, {"severity": "FATAL"}, ["severity"]),
        (Kind.CONGESTION, {"silence_s": 60}, ["silence_s"]),  # propre à une autre règle
        (Kind.TRAFFIC_ANOMALY, {"occupancy_min": 0}, ["occupancy_min"]),
        (Kind.TRAFFIC_ANOMALY, {"occupancy_min": 1.1}, ["occupancy_min"]),
        (Kind.TRAFFIC_ANOMALY, {"queue_min_m": -1}, ["queue_min_m"]),
        (Kind.TRAFFIC_ANOMALY, {"queue_min_m": "150"}, ["queue_min_m"]),
        (Kind.SENSOR_FAULT, {"silence_s": 59}, ["silence_s"]),
        (Kind.SENSOR_FAULT, {"silence_s": 3601}, ["silence_s"]),
        (Kind.SENSOR_FAULT, {"inconnu": 1, "silence_s": 5}, ["inconnu", "silence_s"]),
    ],
)
def test_refused_parameters_are_named(kind, params, bad):
    assert sorted(name for name, _ in invalid_params(kind, params)) == sorted(bad)


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        (Kind.CONGESTION, {"state": "SLOW", "min_windows": 60, "severity": "CRITICAL"}),
        (Kind.TRAFFIC_ANOMALY, {"occupancy_min": 1, "queue_min_m": 10000, "min_windows": 1}),
        (Kind.SENSOR_FAULT, {"silence_s": 60}),
        (Kind.SENSOR_FAULT, {"silence_s": 3600, "severity": "INFO"}),
        (Kind.CONGESTION, {}),
    ],
)
def test_accepted_parameters(kind, params):
    assert invalid_params(kind, params) == []


def test_every_rule_of_the_seed_has_valid_parameters():
    for rule in SEED_RULES:
        assert invalid_params(rule.kind, rule.params) == []


def test_rule_dataclass_defaults():
    assert Rule("abc", Kind.CONGESTION, True, {}, 0).updated_at is None


def test_a_congested_window_hands_over_from_an_anomaly_and_proves_the_sensor_alive():
    """Les trois règles ensemble : une seule ouverture (la congestion), les autres se terminent."""
    decisions = decide(RuleEngine(), congested(0))
    assert kinds(decisions) == [
        ("Open", Kind.CONGESTION),
        ("Resolve", Kind.TRAFFIC_ANOMALY),
        ("Resolve", Kind.SENSOR_FAULT),
    ]


# ------------------------------------------------------------------------------------- annulation
def test_revert_forgets_the_last_window_so_that_its_replay_is_evaluated():
    rule = dataclasses.replace(CONGESTION, params={"state": "CONGESTED", "min_windows": 2})
    engine = RuleEngine()
    decide(engine, congested(0), [rule])
    assert decide(engine, congested(1), [rule]) != []  # 2 fenêtres : ouverture décidée...
    engine.revert()  # ... mais son écriture a échoué
    assert (
        decide(engine, congested(1), [rule]) != []
    )  # le rejeu est évalué de nouveau, série comprise


def test_revert_without_evaluation_does_nothing():
    engine = RuleEngine()
    engine.revert()
    assert decide(engine, congested(0), [CONGESTION]) != []
