"""Réception d'une mesure : valides sur `iot.raw`, invalides sur `errors.dlq`, doublons ignorés."""

import json
import logging
import threading
from datetime import UTC, datetime

import pytest

from app.services.ingestion import (
    TOPIC_ERRORS,
    TOPIC_RAW,
    IngestionService,
    Outcome,
    PublishFailed,
    StoreFailed,
    StripedLocks,
    dumps,
    utc_stamp,
)
from tests.support import FIXED_NOW, Rig, body, contract_errors, measurement, with_value

# --- Une mesure valide ------------------------------------------------------------------------


def test_a_valid_measurement_is_published_on_iot_raw_and_copied_to_mongodb():
    rig = Rig()
    event = measurement(0)
    receipt = rig.service.receive(body(event))
    assert receipt.outcome is Outcome.ACCEPTED
    assert receipt.event_id == event["id"]
    assert rig.publisher.events(TOPIC_RAW) == [event]
    assert list(rig.raw.documents) == [event["id"]]
    assert rig.publisher.events(TOPIC_ERRORS) == []
    assert rig.rejects.documents == []


def test_the_key_is_the_intersection_so_a_crossroad_keeps_its_order():
    rig = Rig()
    rig.service.receive(body(measurement(0)))
    assert rig.publisher.keys(TOPIC_RAW) == ["INT_01"]


def test_the_message_published_is_the_message_received_not_a_rewritten_one():
    rig = Rig()
    event = measurement(0)
    rig.service.receive(body(event))
    (topic, _, value) = rig.publisher.calls[0]
    assert topic == TOPIC_RAW
    assert value == dumps(event)
    assert json.loads(value) == event


def test_the_raw_copy_has_a_real_date_for_time_and_a_reception_date():
    rig = Rig()
    event = measurement(2)
    rig.service.receive(body(event))
    document = rig.raw.documents[event["id"]]
    assert document["time"] == datetime(2026, 10, 20, 8, 0, 30, tzinfo=UTC)
    assert document["received_at"] == FIXED_NOW
    assert document["data"]["provenance"]["source_type"] == "SIMULATED"
    assert {k: v for k, v in document.items() if k not in ("time", "received_at")} == {
        k: v for k, v in event.items() if k != "time"
    }


def test_the_message_is_published_before_it_is_stored():
    rig = Rig()
    rig.service.receive(body(measurement(0)))
    assert rig.trace == ["publish:iot.raw", "insert"]


def test_many_distinct_measurements_all_arrive_once_each():
    rig = Rig()
    events = [measurement(n, sensor) for n in range(20) for sensor in (1, 2, 3)]
    receipts = [rig.service.receive(body(e)) for e in events]
    assert {r.outcome for r in receipts} == {Outcome.ACCEPTED}
    assert [e["id"] for e in rig.publisher.events(TOPIC_RAW)] == [e["id"] for e in events]
    assert len(rig.raw.documents) == 60


# --- Idempotence : un doublon n'est traité qu'une fois ---------------------------------------


def test_the_same_message_twice_is_published_and_stored_once():
    rig = Rig()
    event = measurement(0)
    first = rig.service.receive(body(event))
    second = rig.service.receive(body(event))
    assert (first.outcome, second.outcome) == (Outcome.ACCEPTED, Outcome.DUPLICATE)
    assert second.event_id == event["id"]
    assert len(rig.publisher.events(TOPIC_RAW)) == 1
    assert len(rig.raw.documents) == 1


def test_a_duplicate_is_not_an_error_and_goes_nowhere_else():
    rig = Rig()
    event = measurement(0)
    for _ in range(5):
        rig.service.receive(body(event))
    assert rig.publisher.events(TOPIC_ERRORS) == []
    assert rig.rejects.documents == []


def test_a_duplicate_is_logged_with_its_id_and_a_counter(caplog):
    caplog.set_level(logging.INFO)
    rig = Rig()
    event = measurement(0)
    rig.service.receive(body(event))
    caplog.clear()
    rig.service.receive(body(event))
    (record,) = [r for r in caplog.records if r.name == "app.ingestion"]
    assert record.message == "doublon ignoré"
    assert record.fields == {"event_id": event["id"], "counter": "duplicates"}


def test_the_same_content_written_differently_is_still_the_same_message():
    rig = Rig()
    event = measurement(0)
    spaced = json.dumps(event, indent=4).encode()
    assert rig.service.receive(body(event)).outcome is Outcome.ACCEPTED
    assert rig.service.receive(spaced).outcome is Outcome.DUPLICATE


def test_the_same_sensor_at_another_instant_is_a_different_message():
    rig = Rig()
    assert rig.service.receive(body(measurement(0))).outcome is Outcome.ACCEPTED
    assert rig.service.receive(body(measurement(1))).outcome is Outcome.ACCEPTED


def test_a_run_replayed_under_another_run_id_is_not_a_duplicate():
    rig = Rig()
    assert rig.service.receive(body(measurement(0, run_id="run-a"))).outcome is Outcome.ACCEPTED
    assert rig.service.receive(body(measurement(0, run_id="run-b"))).outcome is Outcome.ACCEPTED


def test_a_hundred_simultaneous_copies_give_one_publication_and_ninety_nine_duplicates():
    rig = Rig()
    body_ = body(measurement(0))
    outcomes: list[Outcome] = []
    gate = threading.Barrier(100)

    def send() -> None:
        gate.wait()
        outcomes.append(rig.service.receive(body_).outcome)

    threads = [threading.Thread(target=send) for _ in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(Outcome.ACCEPTED) == 1
    assert outcomes.count(Outcome.DUPLICATE) == 99
    assert len(rig.publisher.events(TOPIC_RAW)) == 1
    assert len(rig.raw.documents) == 1


def test_the_lock_per_id_is_what_keeps_simultaneous_copies_to_one_publication():
    """Avec un accusé du broker lent (5 ms), sans le verrou les fils publieraient tous."""
    rig = Rig()
    rig.publisher.delay_s = 0.005
    raw = body(measurement(0))
    outcomes: list[Outcome] = []
    gate = threading.Barrier(20)

    def send() -> None:
        gate.wait()
        outcomes.append(rig.service.receive(raw).outcome)

    threads = [threading.Thread(target=send) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(rig.publisher.events(TOPIC_RAW)) == 1
    assert outcomes.count(Outcome.ACCEPTED) == 1


def test_a_rejection_message_that_would_break_its_own_contract_is_not_published():
    """Garde-fou : un message d'erreur mal construit est une erreur, pas un message hors contrat."""
    from pydantic import ValidationError

    from app.services.validation import Rejection

    rig = Rig()
    with pytest.raises(ValidationError):
        rig.service._reject(Rejection("CONTRACT_VIOLATION", "", {}), None)  # motif vide : interdit
    assert rig.publisher.calls == []
    assert rig.rejects.documents == []


def test_simultaneous_distinct_messages_are_not_confused_with_duplicates():
    rig = Rig()
    events = [measurement(n, sensor) for n in range(10) for sensor in range(1, 11)]
    outcomes: list[Outcome] = []
    lock = threading.Lock()

    def send(chunk: list[dict]) -> None:
        for event in chunk:
            outcome = rig.service.receive(body(event)).outcome
            with lock:
                outcomes.append(outcome)

    threads = [threading.Thread(target=send, args=(events[i::10],)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(Outcome.ACCEPTED) == 100
    assert len(rig.publisher.events(TOPIC_RAW)) == 100


def test_when_another_instance_wins_the_race_the_late_one_reports_a_duplicate(caplog):
    """Deux instances, même message : l'index unique de MongoDB tranche, la perdante le dit."""
    rig = Rig()
    event = measurement(0)
    original_exists = rig.raw.exists

    def exists_then_someone_else_stores(event_id: str) -> bool:
        found = original_exists(event_id)
        rig.raw.documents[event_id] = {"id": event_id}  # l'autre instance écrit juste après
        return found

    rig.raw.exists = exists_then_someone_else_stores  # type: ignore[method-assign]
    receipt = rig.service.receive(body(event))
    assert receipt.outcome is Outcome.DUPLICATE
    assert "double publication évitée de justesse" in caplog.text


def test_striped_locks_give_the_same_lock_to_the_same_id_and_a_known_number_of_locks():
    locks = StripedLocks(8)
    assert locks("a") is locks("a")
    assert len({id(locks(f"id-{i}")) for i in range(200)}) == 8


# --- Une mesure invalide ----------------------------------------------------------------------


def invalid() -> dict:
    return with_value(measurement(0), ("data", "occupancy_rate"), 1.7)


def test_an_invalid_measurement_goes_to_the_error_topic_and_never_to_iot_raw():
    rig = Rig()
    receipt = rig.service.receive(body(invalid()))
    assert receipt.outcome is Outcome.REJECTED
    assert rig.publisher.events(TOPIC_RAW) == []
    assert rig.raw.documents == {}
    (dlq,) = rig.publisher.events(TOPIC_ERRORS)
    assert dlq["data"]["reason_code"] == "CONTRACT_VIOLATION"
    assert "occupancy_rate" in dlq["data"]["reason"]


def test_the_error_message_respects_its_own_contract_schema_and_rules():
    rig = Rig()
    rig.service.receive(body(invalid()), correlation_id="corr-abc")
    (dlq,) = rig.publisher.events(TOPIC_ERRORS)
    assert contract_errors(dlq) == []
    assert dlq["type"] == "novaria.error.rejected.v1"
    assert dlq["source"] == "collecte"
    assert dlq["domain"] == "error"
    assert dlq["correlation_id"] == "corr-abc"
    assert dlq["time"] == dlq["data"]["rejected_at"] == utc_stamp(FIXED_NOW)


def test_the_error_message_keeps_the_original_exactly_for_analysis_and_replay():
    rig = Rig()
    original = invalid()
    rig.service.receive(body(original))
    (dlq,) = rig.publisher.events(TOPIC_ERRORS)
    data = dlq["data"]
    assert data["original_payload"] == original
    assert data["source_topic"] == "iot.raw"
    assert data["attempts"] == 1
    assert data["original_key"] == data["intersection_id"] == "INT_01"
    assert dlq["subject"] == "INT_01"


def test_the_error_message_is_keyed_by_the_crossroad_like_the_other_topics():
    rig = Rig()
    rig.service.receive(body(invalid()))
    assert rig.publisher.keys(TOPIC_ERRORS) == ["INT_01"]


def test_an_unreadable_message_is_kept_as_text_with_subject_unknown():
    rig = Rig()
    receipt = rig.service.receive(b'{"id": "run-test:SENSOR_001:17')
    assert receipt.outcome is Outcome.REJECTED
    assert receipt.event_id is None
    (dlq,) = rig.publisher.events(TOPIC_ERRORS)
    assert contract_errors(dlq) == []
    assert dlq["subject"] == "UNKNOWN"
    assert dlq["data"]["reason_code"] == "UNREADABLE"
    assert dlq["data"]["original_payload"] == '{"id": "run-test:SENSOR_001:17'
    assert dlq["data"]["intersection_id"] is None
    assert rig.publisher.keys(TOPIC_ERRORS) == ["UNKNOWN"]


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda: with_value(measurement(0), ("type",), "novaria.autre.v1"), "UNKNOWN_TYPE"),
        (lambda: with_value(measurement(0), ("subject",), "INT_02"), "SEMANTIC_VIOLATION"),
        (lambda: [1, 2, 3], "CONTRACT_VIOLATION"),
    ],
)
def test_each_reason_family_gives_a_valid_error_message(make, code):
    rig = Rig()
    rig.service.receive(body(make()))
    (dlq,) = rig.publisher.events(TOPIC_ERRORS)
    assert contract_errors(dlq) == []
    assert dlq["data"]["reason_code"] == code


def test_the_rejection_is_archived_in_mongodb_with_the_fields_of_the_dictionary():
    rig = Rig()
    original = invalid()
    rig.service.receive(body(original), correlation_id="corr-abc")
    (archive,) = rig.rejects.documents
    (dlq,) = rig.publisher.events(TOPIC_ERRORS)
    assert archive["source_topic"] == "iot.raw"
    assert archive["rejected_at"] == FIXED_NOW
    assert archive["reason"] == dlq["data"]["reason"] != ""
    assert archive["reason_code"] == "CONTRACT_VIOLATION"
    assert archive["service"] == "collecte"
    assert archive["attempts"] == 1
    assert archive["original_payload"] == original
    assert archive["event_id"] == dlq["id"]
    assert archive["correlation_id"] == "corr-abc"


def test_the_id_of_the_rejected_message_is_returned_when_it_has_one():
    rig = Rig()
    original = invalid()
    assert rig.service.receive(body(original)).event_id == original["id"]


def test_every_rejection_has_its_own_id_even_in_the_same_millisecond():
    rig = Rig()
    for _ in range(50):
        rig.service.receive(body(invalid()))
    ids = [e["id"] for e in rig.publisher.events(TOPIC_ERRORS)]
    assert len(ids) == len(set(ids)) == 50
    assert all(i.startswith("dlq:collecte:iot.raw:") for i in ids)


def test_a_correlation_id_is_made_up_when_none_is_given():
    rig = Rig()
    rig.service.receive(body(invalid()))
    (dlq,) = rig.publisher.events(TOPIC_ERRORS)
    assert dlq["correlation_id"].startswith("corr-")


def test_an_invalid_message_sent_twice_goes_to_the_error_topic_twice():
    """Un rejet n'est pas dédoublonné : chaque tentative laisse sa trace pour l'analyse."""
    rig = Rig()
    for _ in range(2):
        rig.service.receive(body(invalid()))
    assert len(rig.publisher.events(TOPIC_ERRORS)) == 2


def test_the_whole_acceptance_criterion_valid_to_iot_raw_invalid_to_errors_duplicates_ignored():
    rig = Rig()
    valid = [measurement(n, sensor) for n in range(5) for sensor in (1, 2)]
    broken = [with_value(measurement(50 + n), ("data", "vehicle_count"), -n - 1) for n in range(4)]
    stream = [body(e) for e in valid] + [b"pas du json"] + [body(e) for e in broken]
    stream += [body(e) for e in valid[:3]] * 2  # trois mesures renvoyées deux fois de plus
    receipts = [rig.service.receive(raw) for raw in stream]
    counts = {o: sum(r.outcome is o for r in receipts) for o in Outcome}
    assert counts == {Outcome.ACCEPTED: 10, Outcome.REJECTED: 5, Outcome.DUPLICATE: 6}
    assert [e["id"] for e in rig.publisher.events(TOPIC_RAW)] == [e["id"] for e in valid]
    assert len(rig.publisher.events(TOPIC_ERRORS)) == 5
    assert len(rig.raw.documents) == 10
    assert len(rig.rejects.documents) == 5
    rig.publisher.assert_all_conform()


# --- Pannes : rien n'est perdu ----------------------------------------------------------------


def test_when_the_broker_is_down_nothing_is_stored_so_the_sender_can_resend():
    rig = Rig()
    rig.publisher.fail_on = {TOPIC_RAW}
    event = measurement(0)
    with pytest.raises(PublishFailed):
        rig.service.receive(body(event))
    assert rig.raw.documents == {}
    rig.publisher.fail_on = set()
    assert rig.service.receive(body(event)).outcome is Outcome.ACCEPTED
    assert len(rig.publisher.events(TOPIC_RAW)) == 1


def test_when_mongodb_is_down_before_the_lookup_nothing_is_published():
    rig = Rig()
    rig.raw.fail_exists = True
    with pytest.raises(StoreFailed):
        rig.service.receive(body(measurement(0)))
    assert rig.publisher.calls == []


def test_when_mongodb_fails_after_publication_the_resend_is_accepted_not_lost():
    """Au moins une fois : la mesure est sur iot.raw, le client renvoie, le traitement filtre."""
    rig = Rig()
    event = measurement(0)
    rig.raw.fail_insert = True
    with pytest.raises(StoreFailed):
        rig.service.receive(body(event))
    assert len(rig.publisher.events(TOPIC_RAW)) == 1
    assert rig.raw.documents == {}
    rig.raw.fail_insert = False
    assert rig.service.receive(body(event)).outcome is Outcome.ACCEPTED
    assert len(rig.raw.documents) == 1
    assert len(rig.publisher.events(TOPIC_RAW)) == 2  # le seul cas de double publication


def test_when_the_error_topic_is_down_the_rejection_is_not_silently_lost():
    rig = Rig()
    rig.publisher.fail_on = {TOPIC_ERRORS}
    with pytest.raises(PublishFailed):
        rig.service.receive(body(invalid()))
    assert rig.rejects.documents == [], "rien n'est archivé tant que le message n'est pas parti"


def test_when_only_the_archive_fails_the_rejection_still_counts_and_is_logged(caplog):
    rig = Rig()
    rig.rejects.fail = True
    receipt = rig.service.receive(body(invalid()))
    assert receipt.outcome is Outcome.REJECTED
    assert len(rig.publisher.events(TOPIC_ERRORS)) == 1
    assert "copie du rejet non écrite" in caplog.text


def test_a_failure_while_publishing_never_leaves_a_message_on_the_wrong_topic():
    rig = Rig()
    rig.publisher.fail_on = {TOPIC_RAW}
    with pytest.raises(PublishFailed):
        rig.service.receive(body(measurement(0)))
    assert rig.publisher.events(TOPIC_ERRORS) == []


def test_the_service_is_stateless_a_new_instance_sees_the_same_world():
    """Les doublons se reconnaissent dans MongoDB, pas dans la mémoire d'une instance."""
    rig = Rig()
    event = measurement(0)
    rig.service.receive(body(event))
    other = IngestionService(
        rig.publisher, rig.raw, rig.rejects, max_bytes=65536, clock=lambda: FIXED_NOW
    )
    assert other.receive(body(event)).outcome is Outcome.DUPLICATE
    assert len(rig.publisher.events(TOPIC_RAW)) == 1
