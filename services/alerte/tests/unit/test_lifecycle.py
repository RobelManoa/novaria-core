"""Cycle de vie d'une alerte : transitions, atomicité, anti-bruit (RG-16 à RG-19, MS-11)."""

from contextlib import contextmanager

import pytest

from app.domain.model import Kind, Open, Resolve, State
from app.schemas.events import IndicatorEvent
from app.services.alerts import OpenOutcome, check_transition
from app.services.events import build_event, event_id
from app.services.ingestion import to_window
from app.services.ports import InvalidTransition, NotFound, StoreFailed
from tests.support import (
    NOW,
    assert_published_conforms,
    congested,
    contract_errors,
    indicator,
    silent,
)


def open_one(rig, minute=0, **changes):
    rig.feed(congested(minute, **changes))
    return rig.store.alerts(Kind.CONGESTION)


# ------------------------------------------------------------------------------- création
def test_an_alert_is_created_with_history_and_event_in_one_transaction(rig):
    (alert,) = open_one(rig)
    assert alert.state is State.CREATED
    assert alert.cause == "UNKNOWN"  # RG-18 : une baisse de vitesse ne prouve pas un accident
    assert alert.episode_id is None
    assert alert.opened_at.isoformat().startswith("2026-10-20T08:01:00")  # temps d'événement
    assert rig.store.states(alert.alert_id) == ["CREATED"]
    assert [row["event_id"] for row in rig.store.data.outbox] == [
        event_id(alert.alert_id, State.CREATED)
    ]
    assert len(rig.store.data.history) == 1  # une ligne d'historique, un événement, une alerte


def test_the_opening_event_conforms_to_the_contract_and_carries_the_provenance(rig):
    (alert,) = open_one(rig)
    (row,) = rig.store.data.outbox
    event = row["payload"]
    assert contract_errors(event) == []
    assert_published_conforms("alerts.events", event)
    data = event["data"]
    assert (data["state"], data["previous_state"], data["resolved_at"]) == ("CREATED", None, None)
    assert data["provenance"] == {
        "source_type": "SIMULATED", "run_id": "run-test",
        "scenario_id": "heure-de-pointe", "seed": 42,
    }  # fmt: skip
    assert event["subject"] == "INT_01" and row["key"] == "INT_01"
    assert event["correlation_id"] == congested(0)["correlation_id"]


def test_the_history_keeps_the_values_that_triggered_the_alert(rig):
    (alert,) = open_one(rig)
    (_, entry) = rig.store.data.history[0]
    assert entry.actor == "system" and entry.from_state is None
    assert entry.details["indicator_id"] == congested(0)["id"]
    assert entry.details["speed_ratio"] == 0.2


def test_a_second_congested_window_does_not_create_a_second_alert(rig):
    rig.feed(*[congested(m) for m in range(6)])
    assert len(rig.store.alerts()) == 1
    assert len(rig.store.data.outbox) == 1


def test_another_segment_or_another_run_gets_its_own_alert(rig):
    rig.feed(congested(0), congested(0, segment="ROAD_002"), congested(0, run="run-b"))
    assert len(rig.store.alerts()) == 3


def test_the_unique_index_arbitrates_a_race_between_two_instances(rig):
    """Une autre instance a ouvert l'alerte entre la recherche et l'écriture : refus d'insertion."""
    decision = next(d for d in _decisions(rig, congested(0)) if isinstance(d, Open))
    first = rig.service.open(decision)
    original = rig.store.transaction
    seen = []

    class Racing:
        def __init__(self, tx):
            self._tx = tx

        def __getattr__(self, name):
            return getattr(self._tx, name)

        def open_alert(self, *args, **kwargs):  # la recherche ne voit rien : l'autre n'a pas validé
            seen.append(True)
            return None

        def last_alert(self, *args):
            return None

    @contextmanager
    def racing():
        with original() as tx:
            yield Racing(tx)

    rig.store.transaction = racing
    second = rig.service.open(decision)
    assert (first, second) == (OpenOutcome.CREATED, OpenOutcome.EXISTS)
    assert len(rig.store.alerts()) == 1 and seen


def _decisions(rig, event):
    return rig.engine.evaluate(to_window(IndicatorEvent.model_validate(event)), rig.store.rules())


# ----------------------------------------------------------------------------------- min_gap_s
def test_a_new_alert_waits_min_gap_s_after_the_previous_one_opened(rig):
    rig.feed(congested(0))  # ouverte à 08:01
    rig.feed(indicator(1, "FREE_FLOW"))  # résolue à 08:02
    rig.feed(congested(2))  # 08:03 : 120 s après l'ouverture, moins que 300 s
    assert len(rig.store.alerts(Kind.CONGESTION)) == 1
    assert rig.store.alerts(Kind.CONGESTION)[0].state is State.RESOLVED


def test_the_suppressed_alert_is_created_once_the_gap_has_elapsed(rig):
    rig.feed(congested(0), indicator(1, "FREE_FLOW"), congested(2))
    rig.feed(congested(3), congested(4))  # 08:04 : 180 s, 08:05 : 240 s
    assert len(rig.store.alerts(Kind.CONGESTION)) == 1
    rig.feed(congested(5))  # 08:06 : 300 s exactement : permis
    alerts = sorted(rig.store.alerts(Kind.CONGESTION), key=lambda a: a.opened_at)
    assert [a.state for a in alerts] == [State.RESOLVED, State.CREATED]


def test_min_gap_s_is_counted_per_segment(rig):
    rig.feed(congested(0), indicator(1, "FREE_FLOW"))
    rig.feed(congested(2, segment="ROAD_002"))
    assert len(rig.store.alerts(Kind.CONGESTION)) == 2


def test_min_gap_s_zero_allows_an_immediate_new_alert(rig):
    rig.store.update_rule("congestion.persistante", enabled=None, params=None, min_gap_s=0)
    rig.feed(congested(0), indicator(1, "FREE_FLOW"), congested(2))
    assert len(rig.store.alerts(Kind.CONGESTION)) == 2


# --------------------------------------------------------------------------------- résolution
def test_the_return_to_free_flow_resolves_the_alert_automatically(rig):
    rig.feed(congested(0), *[congested(m) for m in range(1, 4)], indicator(4, "FREE_FLOW"))
    (alert,) = rig.store.alerts(Kind.CONGESTION)
    assert alert.state is State.RESOLVED and alert.resolution == "AUTO"
    assert alert.resolved_at.isoformat().startswith("2026-10-20T08:05:00")
    assert alert.resolved_at >= alert.opened_at
    last = rig.store.data.outbox[-1]["payload"]
    assert last["data"]["state"] == "RESOLVED" and last["data"]["resolution"] == "AUTO"
    assert contract_errors(last) == []


def test_resolving_without_an_open_alert_does_nothing(rig):
    rig.feed(indicator(0, "FREE_FLOW"))
    assert rig.store.data.outbox == [] and rig.store.alerts() == []


def test_an_old_indicator_cannot_resolve_before_the_opening(rig):
    """La base exige resolved_at >= opened_at : un indicateur ancien est ramené à l'ouverture."""
    rig.feed(congested(10))
    from app.domain.rules import RuleEngine

    window = to_window(IndicatorEvent.model_validate(indicator(1, "FREE_FLOW")))
    decision = next(
        d for d in RuleEngine().evaluate(window, rig.store.rules()) if isinstance(d, Resolve)
    )
    alert = rig.service.resolve_auto(decision)
    assert alert.resolved_at == alert.opened_at


# ------------------------------------------------------------------------------- notification
def test_the_notification_moves_created_to_notified(rig):
    (alert,) = open_one(rig)
    moved = rig.service.mark_notified(alert.alert_id)
    assert moved.state is State.NOTIFIED and moved.notified_at == NOW
    assert rig.store.states(alert.alert_id) == ["CREATED", "NOTIFIED"]
    event = rig.store.data.outbox[-1]["payload"]
    assert event["data"]["previous_state"] == "CREATED"
    assert event["id"] == event_id(alert.alert_id, State.NOTIFIED)
    assert contract_errors(event) == []


def test_a_notification_arriving_after_the_acknowledgement_is_skipped(rig):
    (alert,) = open_one(rig)
    rig.service.acknowledge(alert.alert_id, "op-1")
    assert rig.service.mark_notified(alert.alert_id) is None
    assert rig.store.alerts()[0].state is State.ACKNOWLEDGED  # jamais de retour en arrière


def test_marking_an_unknown_alert_notified_does_nothing(rig):
    assert rig.service.mark_notified("00000000-0000-4000-8000-0000000000ff") is None


# --------------------------------------------------------------------------- opérateur
def test_acknowledge_from_created_or_notified(rig):
    (alert,) = open_one(rig)
    acknowledged, changed = rig.service.acknowledge(alert.alert_id, "user-7")
    assert changed and acknowledged.state is State.ACKNOWLEDGED
    assert (acknowledged.acknowledged_by, acknowledged.acknowledged_at) == ("user-7", NOW)
    rig.feed(congested(0, segment="ROAD_002"))
    other = next(a for a in rig.store.alerts() if a.road_segment_id == "ROAD_002")
    rig.service.mark_notified(other.alert_id)
    _, changed = rig.service.acknowledge(other.alert_id, "user-7")
    assert changed
    assert rig.store.states(other.alert_id) == ["CREATED", "NOTIFIED", "ACKNOWLEDGED"]


def test_acknowledging_twice_changes_nothing_and_writes_no_event(rig):
    (alert,) = open_one(rig)
    rig.service.acknowledge(alert.alert_id, "user-7")
    events_before = len(rig.store.data.outbox)
    again, changed = rig.service.acknowledge(alert.alert_id, "user-8")
    assert not changed and again.acknowledged_by == "user-7"
    assert len(rig.store.data.outbox) == events_before


def test_acknowledging_a_resolved_alert_is_refused(rig):
    rig.feed(congested(0), indicator(1, "FREE_FLOW"))
    (alert,) = rig.store.alerts(Kind.CONGESTION)
    with pytest.raises(InvalidTransition) as error:
        rig.service.acknowledge(alert.alert_id, "user-7")
    assert (error.value.current, error.value.target) == (State.RESOLVED, State.ACKNOWLEDGED)


def test_manual_resolution_records_who_and_why(rig):
    (alert,) = open_one(rig)
    resolved = rig.service.resolve_manual(alert.alert_id, "user-7", "route dégagée par les agents")
    assert resolved.state is State.RESOLVED and resolved.resolution == "MANUAL"
    assert resolved.resolved_at == NOW and resolved.resolved_at >= resolved.opened_at
    entry = rig.store.data.history[-1][1]
    assert (entry.actor, entry.details) == ("user-7", {"comment": "route dégagée par les agents"})
    assert contract_errors(rig.store.data.outbox[-1]["payload"]) == []


def test_manual_resolution_without_comment_has_no_details(rig):
    (alert,) = open_one(rig)
    rig.service.resolve_manual(alert.alert_id, "user-7")
    assert rig.store.data.history[-1][1].details is None


def test_resolving_a_resolved_alert_is_refused(rig):
    (alert,) = open_one(rig)
    rig.service.resolve_manual(alert.alert_id, "user-7")
    with pytest.raises(InvalidTransition):
        rig.service.resolve_manual(alert.alert_id, "user-7")


def test_manual_resolution_in_the_simulated_future_never_precedes_the_opening(rig):
    """Un run simulé daté après l'horloge du service : resolved_at reste >= opened_at (CHECK)."""
    from datetime import timedelta

    rig.clock.current -= timedelta(days=60)
    (alert,) = open_one(rig)
    resolved = rig.service.resolve_manual(alert.alert_id, "user-7")
    assert resolved.resolved_at == resolved.opened_at


def test_unknown_alerts_are_not_found(rig):
    with pytest.raises(NotFound):
        rig.service.acknowledge("00000000-0000-4000-8000-0000000000ff", "u")
    with pytest.raises(NotFound):
        rig.service.resolve_manual("00000000-0000-4000-8000-0000000000ff", "u")


# -------------------------------------------------------------------------------- atomicité
def test_a_failed_outbox_write_cancels_the_alert_and_its_history(rig):
    """RG-17 : pas de changement sans événement. Rien de la transaction n'est gardé."""
    rig.store.fail_outbox = True
    with pytest.raises(StoreFailed):
        rig.feed(congested(0))
    assert rig.store.alerts() == [] and rig.store.data.history == []
    rig.store.fail_outbox = False
    rig.feed(congested(0))  # le même indicateur rejoué crée l'alerte
    assert len(rig.store.alerts()) == 1


def test_a_failed_outbox_write_cancels_a_transition_too(rig):
    (alert,) = open_one(rig)
    rig.store.fail_outbox = True
    with pytest.raises(StoreFailed):
        rig.service.acknowledge(alert.alert_id, "user-7")
    assert rig.store.alerts()[0].state is State.CREATED
    assert rig.store.states(alert.alert_id) == ["CREATED"]


# ---------------------------------------------------------------------------------- transitions
@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (State.CREATED, State.NOTIFIED, True),
        (State.CREATED, State.ACKNOWLEDGED, True),
        (State.CREATED, State.RESOLVED, True),
        (State.NOTIFIED, State.ACKNOWLEDGED, True),
        (State.NOTIFIED, State.RESOLVED, True),
        (State.ACKNOWLEDGED, State.RESOLVED, True),
        (State.NOTIFIED, State.CREATED, False),  # jamais de retour en arrière
        (State.ACKNOWLEDGED, State.NOTIFIED, False),
        (State.RESOLVED, State.ACKNOWLEDGED, False),
        (State.RESOLVED, State.RESOLVED, False),
        (State.CREATED, State.CREATED, False),  # ni de rejeu du même état
    ],
)
def test_transitions_only_go_forward(current, target, allowed):
    if allowed:
        check_transition(current, target)
    else:
        with pytest.raises(InvalidTransition):
            check_transition(current, target)


def test_event_ids_are_stable_and_distinct_per_state():
    ids = {event_id("abc", state) for state in State}
    assert len(ids) == 4 and event_id("abc", State.NOTIFIED) == "alerte-abc-notified"


def test_an_event_is_built_from_the_alert_as_it_is_now(rig):
    (alert,) = open_one(rig)
    event = build_event(alert, None, NOW)
    assert event["time"] == "2026-11-05T09:30:00Z"
    assert "correlation_id" in event
    no_correlation = build_event(alert.evolve(correlation_id=None), None, NOW)
    assert "correlation_id" not in no_correlation


def test_every_event_of_a_full_life_conforms(rig):
    rig.feed(congested(0))
    (alert,) = rig.store.alerts()
    rig.service.mark_notified(alert.alert_id)
    rig.service.acknowledge(alert.alert_id, "user-7")
    rig.feed(indicator(1, "FREE_FLOW"))
    events = [row["payload"] for row in rig.store.data.outbox]
    assert [e["data"]["state"] for e in events] == [
        "CREATED",
        "NOTIFIED",
        "ACKNOWLEDGED",
        "RESOLVED",
    ]
    assert [e["data"]["previous_state"] for e in events] == [
        None,
        "CREATED",
        "NOTIFIED",
        "ACKNOWLEDGED",
    ]
    for event in events:
        assert_published_conforms("alerts.events", event)


def test_sensor_fault_alerts_have_their_own_kind_and_unknown_cause(rig):
    rig.feed(silent(0))
    (alert,) = rig.store.alerts()
    assert (alert.kind, alert.rule_id, alert.cause) == (
        Kind.SENSOR_FAULT, "capteur.muet", "UNKNOWN",
    )  # fmt: skip
