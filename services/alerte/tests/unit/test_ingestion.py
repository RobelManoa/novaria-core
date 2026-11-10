"""Traitement d'un message de `traffic.indicators` : rejets, scénarios de bout en bout (MS-11)."""

import copy
import json

import pytest

from app.domain.model import Kind, State
from app.services.ports import PublishFailed, StoreFailed
from tests.support import (
    assert_published_conforms,
    body,
    congested,
    contract_errors,
    indicator,
    silent,
)


# ------------------------------------------------------------------------------------- rejets
def rejection_of(rig):
    (event,) = rig.publisher.on("errors.dlq")
    assert_published_conforms("errors.dlq", event)
    return event


def test_unreadable_bytes_are_rejected_with_their_text(rig):
    result = rig.handler.handle(b"\xff\xfe pas du json", b"INT_01")
    assert result.rejected == "UNREADABLE"
    event = rejection_of(rig)
    assert event["data"]["reason_code"] == "UNREADABLE"
    assert isinstance(event["data"]["original_payload"], str)
    assert event["subject"] == "UNKNOWN" and event["data"]["original_key"] == "INT_01"


@pytest.mark.parametrize("text", [b'{"a": NaN}', b'{"a": Infinity}', b"[" * 2_000_000])
def test_non_strict_or_hopeless_json_is_unreadable_not_a_crash(rig, text):
    assert rig.handler.handle(text).rejected == "UNREADABLE"
    assert contract_errors(rig.publisher.on("errors.dlq")[0]) == []


def test_a_very_long_unreadable_message_is_kept_truncated(rig):
    rig.handler.handle(b"x" * 50000)
    assert len(rejection_of(rig)["data"]["original_payload"]) == 20000


def test_a_message_of_another_type_is_rejected_unknown_type(rig):
    event = indicator(0)
    event["type"] = "novaria.iot.measurement.v1"
    assert rig.handler.handle(body(event)).rejected == "UNKNOWN_TYPE"
    rejected = rejection_of(rig)
    assert rejected["subject"] == "INT_01" and rejected["data"]["intersection_id"] == "INT_01"
    assert rig.store.alerts() == []


def test_a_missing_type_is_unknown_type_too(rig):
    event = indicator(0)
    del event["type"]
    assert rig.handler.handle(body(event)).rejected == "UNKNOWN_TYPE"


def test_an_indicator_out_of_contract_is_rejected_with_the_field_in_the_reason(rig):
    event = indicator(0)
    event["data"]["window_size_s"] = 120
    assert rig.handler.handle(body(event), b"INT_01").rejected == "CONTRACT_VIOLATION"
    rejected = rejection_of(rig)
    assert rejected["data"]["reason"].startswith("data/window_size_s")
    assert rejected["data"]["original_payload"]["data"]["window_size_s"] == 120
    assert rig.store.alerts() == []


def test_several_defects_are_counted_in_the_reason(rig):
    event = indicator(0)
    event["data"]["window_size_s"] = 120
    event["data"]["vehicle_count"] = -1
    rig.handler.handle(body(event))
    assert "(et 1 autre(s))" in rejection_of(rig)["data"]["reason"]


def test_the_rejected_value_is_not_copied_into_the_reason(rig):
    event = indicator(0)
    event["data"]["road_segment_id"] = "valeur-secrete-à-ne-pas-recopier"
    rig.handler.handle(body(event))
    assert "valeur-secrete" not in rejection_of(rig)["data"]["reason"]


@pytest.mark.parametrize("payload", [b"[1, 2]", b'"texte"', b"42", b"null"])
def test_json_that_is_not_an_object_is_a_contract_violation(rig, payload):
    assert rig.handler.handle(payload).rejected == "CONTRACT_VIOLATION"
    assert rig.publisher.on("errors.dlq")[0]["subject"] == "UNKNOWN"


def test_a_subject_that_is_not_an_intersection_becomes_unknown(rig):
    event = indicator(0)
    event["subject"] = "intersection-12"
    rig.handler.handle(body(event))
    assert rejection_of(rig)["subject"] == "UNKNOWN"


def test_a_rejection_waits_for_the_broker_acknowledgement(rig):
    rig.handler.handle(b"pas du json")
    assert rig.publisher.flushes == 1


def test_a_failing_bus_stops_on_a_rejection_instead_of_losing_it(rig):
    rig.publisher.fail = True
    with pytest.raises(PublishFailed):
        rig.handler.handle(b"pas du json")


def test_a_rejected_message_never_reaches_the_rules(rig):
    rig.handler.handle(b"pas du json")
    assert rig.store.transactions == 0


# -------------------------------------------------------------------- scénario de congestion
def test_one_simulated_congestion_raises_one_alert_resolved_automatically(rig):
    """Critère de MS-11 au niveau du service : fluide, congestion de 5 minutes, retour au fluide."""
    series = (
        [indicator(m, "FREE_FLOW") for m in range(2)]
        + [congested(m) for m in range(2, 7)]
        + [indicator(m, "FREE_FLOW") for m in range(7, 10)]
    )
    events = rig.play(*series)

    assert [e["data"]["state"] for e in events] == ["CREATED", "NOTIFIED", "RESOLVED"]
    (alert,) = rig.store.alerts()
    assert alert.kind is Kind.CONGESTION and alert.state is State.RESOLVED
    assert alert.resolution == "AUTO" and alert.cause == "UNKNOWN"
    assert alert.opened_at.isoformat().startswith("2026-10-20T08:03:00")  # fin de la 1re fenêtre
    assert alert.resolved_at.isoformat().startswith("2026-10-20T08:08:00")
    assert [a.alert_id for a in rig.channel.delivered] == [alert.alert_id]  # une seule notification
    assert rig.store.states(alert.alert_id) == ["CREATED", "NOTIFIED", "RESOLVED"]
    for event in events:
        assert_published_conforms("alerts.events", event)
    assert all(e["data"]["alert_id"] == alert.alert_id for e in events)


def test_events_are_published_in_order_and_keyed_by_intersection(rig):
    rig.play(congested(0), indicator(1, "FREE_FLOW"))
    sent = [(t, k) for t, k, _ in rig.publisher.sent]
    assert sent and all(t == "alerts.events" and k == "INT_01" for t, k in sent)
    ids = [e["id"] for e in rig.publisher.on("alerts.events")]
    assert len(ids) == len(set(ids))


def test_replaying_the_whole_series_changes_nothing(rig):
    series = [congested(m) for m in range(4)] + [indicator(4, "FREE_FLOW")]
    rig.play(*series)
    before = (len(rig.store.alerts()), len(rig.store.data.outbox), len(rig.channel.delivered))
    rig.engine.__init__()  # un redémarrage du travailleur : la mémoire des séries est perdue
    rig.play(*series)
    assert (
        len(rig.store.alerts()),
        len(rig.store.data.outbox),
        len(rig.channel.delivered),
    ) == before


def test_an_indicator_redelivered_after_a_store_failure_is_still_evaluated(rig):
    rig.store.fail_outbox = True
    with pytest.raises(StoreFailed):
        rig.feed(congested(0))
    rig.store.fail_outbox = False
    rig.feed(congested(0))  # même message, même processus : l'alerte est créée
    assert len(rig.store.alerts()) == 1


def test_a_congestion_resumed_after_a_gap_does_not_flicker(rig):
    """CE-13 : nouvelle congestion sur un tronçon qui a une alerte non résolue : pas de seconde."""
    rig.run(congested(0), congested(1), silent(2), congested(3), congested(4))
    assert len(rig.store.alerts(Kind.CONGESTION)) == 1


def test_the_five_minute_windows_do_not_duplicate_the_alert(rig):
    rig.run(congested(0), congested(0, size=300), congested(1))
    assert len(rig.store.alerts(Kind.CONGESTION)) == 1


def test_a_mute_sensor_raises_a_sensor_fault_and_never_a_congestion(rig):
    """CE-12 / EXG-ALE-04 : le silence d'un capteur n'est pas une route arrêtée."""
    events = rig.play(indicator(0), silent(1), silent(2))
    (alert,) = rig.store.alerts()
    assert alert.kind is Kind.SENSOR_FAULT and alert.rule_id == "capteur.muet"
    assert rig.store.alerts(Kind.CONGESTION) == []
    assert events[0]["data"]["kind"] == "SENSOR_FAULT"
    rig.play(indicator(3))  # les mesures reviennent : résolue
    assert rig.store.alerts()[0].state is State.RESOLVED


def test_a_saturated_but_fluid_segment_raises_a_traffic_anomaly(rig):
    rig.run(*[indicator(m, "FREE_FLOW", occupancy=0.92) for m in range(3)])
    (alert,) = rig.store.alerts()
    assert (alert.kind, alert.severity.value) == (Kind.TRAFFIC_ANOMALY, "INFO")


def test_a_congestion_with_high_occupancy_raises_one_alert_not_two(rig):
    """Le simulateur sature l'occupation pendant une congestion : l'anomalie ne s'ajoute pas."""
    series = [indicator(m, "FREE_FLOW", occupancy=0.5) for m in range(2)]
    series += [congested(m, occupancy=0.95, queue=240.0) for m in range(2, 8)]
    series += [indicator(m, "SLOW", ratio=0.5, occupancy=0.9) for m in range(8, 11)]
    series += [indicator(m, "FREE_FLOW", occupancy=0.4) for m in range(11, 14)]
    rig.play(*series)
    assert [a.kind for a in rig.store.alerts()] == [Kind.CONGESTION]


def test_disabling_a_rule_stops_its_alerts_at_the_next_read_of_the_rules(rig):
    rig.store.update_rule("congestion.persistante", enabled=False, params=None, min_gap_s=None)
    rig.run(congested(0))
    assert rig.store.alerts() == []


def test_the_event_time_is_the_measure_time_not_the_clock_of_the_service(rig):
    rig.run(congested(0))
    opened = json.loads(json.dumps(rig.publisher.on("alerts.events")[0]))["data"]["opened_at"]
    assert opened == "2026-10-20T08:01:00Z"  # le run simulé date du 20/10, le service du 05/11


def test_two_runs_are_independent(rig):
    rig.run(congested(0, run="run-a"), congested(0, run="run-b"))
    runs = sorted(a.provenance.run_id for a in rig.store.alerts())
    assert runs == ["run-a", "run-b"]


def test_alerts_keep_the_provenance_of_their_indicator(rig):
    event = copy.deepcopy(congested(0))
    event["data"]["provenance"] = {
        "source_type": "REAL_HISTORICAL",
        "run_id": "h1",
        "dataset_id": "paris-2024",
    }
    rig.run(event)
    (alert,) = rig.store.alerts()
    assert alert.provenance.dataset_id == "paris-2024" and alert.provenance.seed is None
    assert contract_errors(rig.publisher.on("alerts.events")[0]) == []
