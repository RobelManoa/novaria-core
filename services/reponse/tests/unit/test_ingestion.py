"""Un message de `traffic.recommendations` : lu, rejeté (DLQ) ou soumis aux garde-fous."""

import json

import pytest
from conformance import assert_publication

from app.domain.model import Mode
from app.domain.safety import Phase
from tests.support import Rig, plan, raw, recommendation_event


def dlq(rig: Rig) -> list[dict]:
    rig.flush()
    return rig.publisher.on("errors.dlq")


def test_a_valid_recommendation_is_applied():
    rig = Rig()
    assert rig.handler.handle(raw(recommendation_event())) == "APPLIED"
    assert rig.service.view("INT_01").mode is Mode.AUTOMATIC
    assert dlq(rig) == []


def test_a_dangerous_but_valid_recommendation_is_refused_not_rejected():
    rig = Rig()
    bad = recommendation_event(phases=[Phase("P1", ("N", "E"), 30), Phase("P2", ("S", "W"), 30)])
    assert rig.handler.handle(raw(bad)) == "REFUSED"
    assert dlq(rig) == []  # ce n'est pas une erreur du bus : le refus est sur signal.status
    assert rig.status()[-1]["data"]["decision"]["refusal_reason"] == "CONFLICTING_GREENS"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"\xff\xfe pas du texte", "UNREADABLE"),
        (b"{pas du json", "UNREADABLE"),
        (b'{"a": NaN}', "UNREADABLE"),
        (raw({"type": "novaria.iot.measurement.v1"}), "UNKNOWN_TYPE"),
        (raw({"type": "novaria.traffic.recommendation.v1", "id": "x"}), "CONTRACT_VIOLATION"),
    ],
)
def test_an_unusable_message_goes_to_the_dead_letter_topic_and_stops_nothing(payload, code):
    rig = Rig()
    assert rig.handler.handle(payload, b"INT_01") == f"REJECTED:{code}"
    [rejected] = dlq(rig)
    assert (
        rejected["data"]["reason_code"] == code
        and rejected["data"]["source_topic"] == "traffic.recommendations"
    )
    assert_publication("reponse", "errors.dlq", rejected)
    assert rig.service.view("INT_01").mode is Mode.DEGRADED_FIXED_PLAN  # l'état n'a pas bougé


def test_a_recommendation_for_an_intersection_without_signals_is_rejected_as_semantic():
    rig = Rig()
    assert rig.handler.handle(raw(recommendation_event("INT_09"))) == "REJECTED:SEMANTIC_VIOLATION"
    [rejected] = dlq(rig)
    assert rejected["subject"] == "INT_09" and "INT_09" in rejected["data"]["reason"]


def test_an_unreadable_message_keeps_its_text_and_the_key():
    rig = Rig()
    rig.handler.handle(b"{pas du json", b"INT_02")
    [rejected] = dlq(rig)
    assert rejected["data"]["original_payload"] == "{pas du json"
    assert rejected["data"]["original_key"] == "INT_02" and rejected["subject"] == "UNKNOWN"


def test_a_message_that_is_not_an_object_is_rejected_without_crashing():
    rig = Rig()
    assert rig.handler.handle(b"[1, 2, 3]") == "REJECTED:CONTRACT_VIOLATION"


def test_a_defect_in_the_service_does_not_block_the_next_messages(monkeypatch):
    rig = Rig()

    def broken(event):
        raise RuntimeError("défaut interne")

    monkeypatch.setattr(rig.service, "on_recommendation", broken)
    assert rig.handler.handle(raw(recommendation_event())) == "REJECTED:PROCESSING_FAILED"
    [rejected] = dlq(rig)
    assert "RuntimeError" in rejected["data"]["reason"] and "défaut interne" not in json.dumps(
        rejected
    )


def test_a_huge_unreadable_message_is_truncated():
    rig = Rig()
    rig.handler.handle(b"x" * 100_000)
    [rejected] = dlq(rig)
    assert len(rejected["data"]["original_payload"]) == 20_000


def test_the_plan_of_a_real_traitement_recommendation_is_accepted():
    """Un plan tel que le calcul de Webster le produit (cycle de 60 s) passe les garde-fous."""
    rig = Rig()
    assert rig.handler.handle(raw(recommendation_event(phases=plan(34, 26)))) == "APPLIED"
