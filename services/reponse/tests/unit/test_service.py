"""Le service de réponse : critères de MS-12 (garde-fous, mode dégradé, commande, audit)."""

import threading

import pytest
from conformance import assert_publication
from pydantic import ValidationError

from app.domain.model import Mode
from app.domain.safety import Phase
from app.schemas.events import RecommendationEvent
from app.services.events import status_event
from app.services.ports import CommandNotRecorded, RateLimited, UnknownIntersection
from tests.support import (
    Rig,
    at,
    plan,
    recommendation_event,
    resume,
    set_phase,
)


def rec(event) -> RecommendationEvent:
    return RecommendationEvent.model_validate(event)


def feed(rig: Rig, **kwargs):
    event = recommendation_event(at=(rig.clock().timestamp() - at(0).timestamp()), **kwargs)
    return rig.service.on_recommendation(rec(event)), event


def mode(rig: Rig, intersection="INT_01") -> Mode:
    return rig.service.view(intersection).mode


# =========================================================================== démarrage
def test_every_intersection_announces_its_fixed_plan_at_startup():
    rig = Rig()
    rig.service.start()
    assert rig.flush()
    events = rig.status()
    assert sorted(e["subject"] for e in events) == ["INT_01", "INT_02"]
    for event in events:
        assert event["data"]["decision"]["origin"] == "STARTUP"
        assert event["data"]["mode"] == "DEGRADED_FIXED_PLAN"
        assert [p["duration_s"] for p in event["data"]["phases"]] == [30, 30]
        assert {p["min_duration_s"] for p in event["data"]["phases"]} == {10}
    assert [e["action"] for e in rig.audit.entries] == ["signal.startup"] * 2


def test_every_event_published_respects_the_signal_status_contract():
    rig = Rig()
    rig.service.start()
    feed(rig)
    feed(rig, phases=[Phase("P1", ("N", "E"), 30), Phase("P2", ("S", "W"), 30)])
    rig.advance(12)
    rig.service.command("INT_01", set_phase("P2", 20), role="operator")
    rig.service.command("INT_01", set_phase("P1", 20), role="operator")  # refusée
    rig.advance(400)
    rig.service.stop()
    assert rig.flush()
    assert len(rig.status()) >= 7
    for event in rig.status():
        assert_publication("reponse", "signal.status", event)


# =========================================================================== recommandations
def test_a_safe_recommendation_is_applied_published_and_journaled():
    rig = Rig()
    outcome, event = feed(rig)
    assert outcome == "APPLIED"
    assert mode(rig) is Mode.AUTOMATIC
    rig.flush()
    [status] = rig.status()
    decision = status["data"]["decision"]
    assert (decision["origin"], decision["outcome"], decision["reference_id"]) == (
        "RECOMMENDATION",
        "APPLIED",
        event["data"]["recommendation_id"],
    )
    assert status["correlation_id"] == "corr-rec-1"
    assert status["data"]["provenance"]["run_id"] == "run-1"  # celle de la recommandation
    [entry] = rig.audit.entries
    assert (entry["action"], entry["outcome"], entry["actor"]) == (
        "signal.recommendation",
        "ok",
        "reponse",
    )


@pytest.mark.parametrize(
    ("phases", "reason"),
    [
        ([Phase("P1", ("N", "E"), 30), Phase("P2", ("S", "W"), 30)], "CONFLICTING_GREENS"),
        (
            [Phase("P1", ("N", "S", "E", "W"), 30), Phase("P2", ("E", "W"), 30)],
            "CONFLICTING_GREENS",
        ),
        (plan(5, 30), "PHASE_TOO_SHORT"),
        (plan(30, 200), "PHASE_TOO_LONG"),
        ([Phase("P1", ("N", "S"), 30), Phase("P3", ("E", "W"), 30)], "PHASE_LAYOUT_MISMATCH"),
    ],
)
def test_a_dangerous_recommendation_never_reaches_the_controller_and_is_journaled(phases, reason):
    """Critère : aucune commande qui viole une règle de sécurité n'est appliquée."""
    rig = Rig()
    before = rig.service.view("INT_01")
    outcome, event = feed(rig, phases=phases)
    assert outcome == "REFUSED"
    after = rig.service.view("INT_01")
    assert (after.mode, after.phases, after.phase_ends_at) == (
        before.mode,
        before.phases,
        before.phase_ends_at,
    )
    rig.flush()
    [status] = rig.status()
    decision = status["data"]["decision"]
    assert (decision["outcome"], decision["refusal_reason"]) == ("REFUSED", reason)
    assert decision["reference_id"] == event["data"]["recommendation_id"]
    [entry] = rig.audit.entries
    assert (entry["outcome"], entry["details"]["refusal_reason"]) == ("denied", reason)
    assert entry["details"]["refusal_detail"]  # le texte du motif est dans le journal


def test_a_replayed_recommendation_publishes_nothing_more():
    rig = Rig()
    outcome, event = feed(rig)
    again = rig.service.on_recommendation(rec(event))
    assert (outcome, again) == ("APPLIED", "IGNORED")
    rig.flush()
    assert len(rig.status()) == 1


def test_a_recommendation_for_an_unknown_intersection_is_not_a_service_error():
    rig = Rig()
    with pytest.raises(UnknownIntersection):
        rig.service.on_recommendation(rec(recommendation_event("INT_09")))


# =========================================================================== mode dégradé
def test_losing_the_recommendations_returns_to_the_fixed_plan_and_says_so():
    """Critère : la perte des recommandations ramène au plan fixe."""
    rig = Rig(max_silence_s=120)
    feed(rig)
    rig.advance(119)
    assert mode(rig) is Mode.AUTOMATIC
    rig.advance(1)
    view = rig.service.view("INT_01")
    assert view.mode is Mode.DEGRADED_FIXED_PLAN
    assert [p.duration_s for p in view.phases] == [30, 30]
    rig.flush()
    last = rig.status()[-1]["data"]
    assert (last["mode"], last["decision"]["origin"]) == (
        "DEGRADED_FIXED_PLAN",
        "FIXED_PLAN_FALLBACK",
    )
    assert rig.audit.entries[-1]["action"] == "signal.fixed_plan_fallback"
    rig.advance(600)
    rig.flush()
    assert len(rig.status()) == 2  # une recommandation, un retour au plan fixe : rien de plus


def test_the_fallback_does_not_depend_on_the_bus():
    """Kafka en panne : les feux reviennent quand même au plan fixe, l'événement attend."""
    rig = Rig(max_silence_s=60)
    feed(rig)
    rig.flush()
    rig.publisher.down = True
    rig.advance(61)
    assert mode(rig) is Mode.DEGRADED_FIXED_PLAN
    assert not rig.flush()  # rien ne part
    assert len(rig.outbox) == 1  # mais rien n'est perdu
    rig.publisher.down = False
    assert rig.flush()
    assert [e["data"]["decision"]["origin"] for e in rig.status()] == [
        "RECOMMENDATION",
        "FIXED_PLAN_FALLBACK",
    ]


def test_events_leave_in_the_order_they_were_decided_after_a_bus_outage():
    rig = Rig()
    rig.publisher.down = True
    feed(rig)
    rig.advance(1)
    feed(rig, phases=plan(50, 30))
    assert not rig.flush()
    rig.publisher.down = False
    assert rig.flush()
    refs = [e["data"]["decision"]["reference_id"] for e in rig.status()]
    assert len(refs) == 2 and refs[0] != refs[1]


def test_stopping_the_service_returns_every_busy_intersection_to_the_fixed_plan():
    rig = Rig()
    feed(rig)  # INT_01 en automatique ; INT_02 est déjà au plan fixe
    rig.service.stop()
    rig.flush()
    shutdown = [e for e in rig.status() if e["id"].startswith("reponse-shutdown")]
    assert [e["subject"] for e in shutdown] == ["INT_01"]
    assert shutdown[0]["data"]["mode"] == "DEGRADED_FIXED_PLAN"


def test_stopping_during_a_manual_command_releases_it():
    rig = Rig()
    rig.advance(12)
    rig.service.command("INT_01", set_phase("P2", 60), role="operator")
    rig.service.stop()
    assert mode(rig) is Mode.DEGRADED_FIXED_PLAN


# =========================================================================== commande manuelle
def test_a_safe_manual_command_is_journaled_before_it_acts_then_published():
    rig = Rig()
    rig.advance(12)
    seen_by_audit = []
    original = rig.audit.record

    def spy(entry):
        seen_by_audit.append(mode(rig))  # le mode au moment où le journal est écrit
        original(entry)

    rig.audit.record = spy  # type: ignore[method-assign]
    result = rig.service.command(
        "INT_01",
        set_phase("P2", 30, actor="u-42", reason="évacuation"),
        role="operator",
        correlation_id="c-1",
    )
    assert result.decision.outcome.value == "APPLIED"
    assert mode(rig) is Mode.MANUAL
    assert seen_by_audit == [Mode.MANUAL]  # écrit avec l'état décidé, avant que l'API ne réponde
    [entry] = rig.audit.of("signal.command.")
    assert (
        entry["actor"] == "u-42" and entry["outcome"] == "ok" and entry["correlation_id"] == "c-1"
    )
    for key, value in {
        "intersection_id": "INT_01",
        "phase_id": "P2",
        "duration_s": 30,
        "reason": "évacuation",
        "role": "operator",
        "refusal_reason": None,
    }.items():
        assert entry["details"][key] == value
    rig.flush()
    status = rig.status()[-1]["data"]
    assert (status["mode"], status["decision"]["origin"]) == ("MANUAL", "MANUAL_COMMAND")
    assert status["decision"]["reference_id"] == entry["details"]["command_id"]


@pytest.mark.parametrize(
    ("command", "advance", "reason"),
    [
        (set_phase("P2", 9), 12, "PHASE_TOO_SHORT"),
        (set_phase("P2", 91), 12, "PHASE_TOO_LONG"),
        (set_phase("P7", 30), 12, "UNKNOWN_PHASE"),
        (set_phase("P2", 30), 5, "MIN_DURATION_NOT_ELAPSED"),
        (set_phase("P2", 30), 27, "CLEARANCE_IN_PROGRESS"),
    ],
)
def test_a_dangerous_manual_command_is_refused_journaled_and_published(command, advance, reason):
    """Critère : une commande dangereuse n'est jamais appliquée, et elle laisse une trace."""
    rig = Rig()
    rig.advance(advance)
    before = rig.service.view("INT_01")
    result = rig.service.command("INT_01", command, role="operator")
    assert result.decision.refused and result.decision.refusal_reason == reason
    after = rig.service.view("INT_01")
    assert (after.mode, after.phase_id, after.phase_ends_at) == (
        before.mode,
        before.phase_id,
        before.phase_ends_at,
    )
    [entry] = rig.audit.of("signal.command.")
    assert (entry["outcome"], entry["details"]["refusal_reason"]) == ("denied", reason)
    rig.flush()
    refused = rig.status()[-1]["data"]["decision"]
    assert (refused["outcome"], refused["refusal_reason"]) == ("REFUSED", reason)


def test_a_second_command_during_the_first_is_refused():
    rig = Rig()
    rig.advance(12)
    rig.service.command("INT_01", set_phase("P2", 30), role="operator")
    second = rig.service.command("INT_01", set_phase("P1", 30), role="operator")
    assert second.decision.refusal_reason == "COMMAND_IN_PROGRESS"
    assert mode(rig) is Mode.MANUAL


def test_two_operators_sending_at_the_same_instant_get_exactly_one_command_applied():
    rig = Rig()
    rig.advance(12)
    results, barrier = [], threading.Barrier(8)

    def send(index):
        barrier.wait()
        results.append(
            rig.service.command("INT_01", set_phase("P2", 30, actor=f"u-{index}"), role="operator")
        )

    threads = [threading.Thread(target=send, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    applied = [r for r in results if not r.decision.refused]
    assert len(applied) == 1
    assert {r.decision.refusal_reason for r in results if r.decision.refused} == {
        "COMMAND_IN_PROGRESS"
    }
    assert len(rig.audit.of("signal.command.")) == 8  # chaque tentative est journalisée


def test_a_manual_command_is_not_applied_when_it_cannot_be_journaled():
    """Pas de trace, pas d'effet : l'état est rétabli et rien n'est publié."""
    rig = Rig()
    rig.advance(12)
    rig.flush()
    published = len(rig.status())
    before = rig.service.view("INT_01")
    rig.audit.down = True
    with pytest.raises(CommandNotRecorded):
        rig.service.command("INT_01", set_phase("P2", 30), role="operator")
    after = rig.service.view("INT_01")
    assert (after.mode, after.phase_id, after.phase_ends_at) == (
        before.mode,
        before.phase_id,
        before.phase_ends_at,
    )
    rig.flush()
    assert len(rig.status()) == published
    rig.audit.down = False  # la base revient : la même commande passe
    assert not rig.service.command("INT_01", set_phase("P2", 30), role="operator").decision.refused


def test_a_refusal_stays_a_refusal_when_the_journal_is_down():
    rig = Rig()
    rig.audit.down = True
    result = rig.service.command("INT_01", set_phase("P2", 9), role="operator")
    assert result.decision.refusal_reason == "PHASE_TOO_SHORT"
    assert rig.service.audit_lost == 1
    assert mode(rig) is Mode.DEGRADED_FIXED_PLAN


def test_resuming_automatic_is_a_journaled_command_too():
    rig = Rig()
    feed(rig)
    rig.advance(12)
    rig.service.command("INT_01", set_phase("P2", 60), role="operator")
    rig.advance(20)
    result = rig.service.command("INT_01", resume(actor="u-7"), role="operator")
    assert not result.decision.refused and mode(rig) is Mode.AUTOMATIC
    assert [e["action"] for e in rig.audit.of("signal.command.")] == [
        "signal.command.SET_PHASE",
        "signal.command.RESUME_AUTOMATIC",
    ]


def test_resuming_with_nothing_to_resume_is_journaled_but_publishes_nothing():
    rig = Rig()
    rig.flush()
    result = rig.service.command("INT_01", resume(), role="operator")
    rig.flush()
    assert not result.decision.refused and not result.decision.changed
    assert len(rig.audit.of("signal.command.")) == 1 and rig.status() == []


def test_the_end_of_a_manual_hold_is_reported():
    rig = Rig(max_silence_s=30)
    feed(rig)
    rig.advance(12)
    rig.service.command("INT_01", set_phase("P2", 20), role="operator")
    rig.advance(40)  # la tenue finit à 36 ; la recommandation (30 s) est périmée depuis longtemps
    rig.flush()
    origins = [e["data"]["decision"]["origin"] for e in rig.status()]
    assert origins[-1] == "FIXED_PLAN_FALLBACK" and "MANUAL_COMMAND" in origins


def test_an_unknown_intersection_has_no_signals():
    rig = Rig()
    with pytest.raises(UnknownIntersection):
        rig.service.command("INT_09", set_phase(), role="operator")
    with pytest.raises(UnknownIntersection):
        rig.service.view("INT_09")


# =========================================================================== file d'envoi
def test_the_outbox_is_bounded_and_counts_what_it_drops():
    from app.services.outbox import Outbox, Outgoing

    outbox = Outbox(maxlen=3)
    for index in range(5):
        outbox.put(Outgoing("signal.status", "INT_01", b"{}", f"e{index}"))
    assert [item.event_id for item in outbox.take(10)] == ["e2", "e3", "e4"]
    assert outbox.dropped == 2


def test_a_failed_publication_gives_the_batch_back_in_its_original_order():
    rig = Rig(("INT_01", "INT_02", "INT_03"))
    rig.service.start()
    rig.publisher.down = True
    assert not rig.flush()
    assert len(rig.outbox) == 3
    rig.publisher.down = False
    assert rig.flush()
    assert [e["subject"] for e in rig.status()] == ["INT_01", "INT_02", "INT_03"]


def test_audit_failures_after_publication_are_counted_and_paused_not_fatal():
    rig = Rig()
    rig.audit.down = True
    feed(rig)
    assert rig.flush()  # l'événement part malgré le journal en panne
    assert len(rig.status()) == 1 and rig.service.audit_lost == 1
    rig.advance(1)
    feed(rig, phases=plan(45, 25))
    assert rig.flush()
    assert len(rig.status()) == 2 and rig.service.audit_lost == 2  # en pause : on n'insiste pas


def test_an_invalid_event_is_an_error_not_a_message_on_the_bus():
    rig = Rig()
    view = rig.service.view("INT_01")
    with pytest.raises(ValidationError):
        status_event(
            view,
            view.decision.__class__(view.decision.origin, "pas-un-uuid", view.decision.outcome),
            at(0),
            kind="x",
            correlation_id=None,
        )


# =========================================================================== débit des commandes
def test_an_operator_cannot_hammer_the_signals_with_commands():
    rig = Rig()
    for _ in range(10):
        rig.service.command("INT_01", set_phase("P2", 9, actor="u-1"), role="operator")
    with pytest.raises(RateLimited) as limited:
        rig.service.command("INT_01", set_phase("P2", 9, actor="u-1"), role="operator")
    assert 1 <= limited.value.retry_after_s <= 60
    refused = [
        e
        for e in rig.audit.of("signal.command.")
        if e["details"]["refusal_reason"] == "RATE_LIMITED"
    ]
    assert (
        len(refused) == 1
        and refused[0]["outcome"] == "denied"
        and refused[0]["details"]["role"] == "operator"
    )
    rig.flush()
    assert all(e["data"]["decision"]["refusal_reason"] != "RATE_LIMITED" for e in rig.status())


def test_the_rate_limit_is_per_operator_and_slides_with_time():
    rig = Rig()
    for _ in range(10):
        rig.service.command("INT_01", set_phase("P2", 9, actor="u-1"), role="operator")
    rig.service.command(
        "INT_01", set_phase("P2", 9, actor="u-2"), role="operator"
    )  # un autre : permis
    rig.advance(61)
    rig.service.command(
        "INT_01", set_phase("P2", 9, actor="u-1"), role="operator"
    )  # la minute a passé


def test_a_rate_limited_refusal_is_still_a_refusal_when_the_journal_is_down():
    rig = Rig()
    for _ in range(10):
        rig.service.command("INT_01", set_phase("P2", 9), role="operator")
    rig.audit.down = True
    with pytest.raises(RateLimited):
        rig.service.command("INT_01", set_phase("P2", 30), role="operator")
    assert rig.service.audit_lost == 1


# =========================================================================== détails de publication
def test_a_manual_command_is_journaled_exactly_once():
    rig = Rig()
    rig.advance(12)
    rig.service.command("INT_01", set_phase("P2", 30), role="operator")
    rig.service.command("INT_01", set_phase("P1", 30), role="operator")  # refusée
    rig.flush()
    assert len(rig.audit.entries) == 2  # une entrée par commande, pas une de plus par l'événement


def test_event_ids_are_stable_so_a_replay_is_recognised_downstream():
    rig = Rig()
    _, event = feed(rig)
    rig.advance(12)
    result = rig.service.command("INT_01", set_phase("P2", 30), role="operator")
    rig.flush()
    ids = {e["id"] for e in rig.status()}
    assert f"reponse-recommendation-{event['data']['recommendation_id']}" in ids
    assert f"reponse-command-{result.command.command_id}" in ids


def test_the_validity_announced_by_the_recommendation_bounds_the_wait_when_it_is_shorter():
    rig = Rig(max_silence_s=180)
    feed(rig, validity=40)
    rig.advance(39)
    assert mode(rig) is Mode.AUTOMATIC
    rig.advance(2)
    assert mode(rig) is Mode.DEGRADED_FIXED_PLAN


def test_stopping_reports_a_loss_that_had_not_been_noticed_yet_as_a_fallback_not_a_shutdown():
    rig = Rig(max_silence_s=30)
    feed(rig)
    rig.clock.advance(100)  # personne n'a fait avancer le contrôleur depuis
    rig.service.stop()
    rig.flush()
    ids = [e["id"] for e in rig.status()]
    assert any(i.startswith("reponse-fallback-INT_01") for i in ids)
    assert not any(i.startswith("reponse-shutdown-INT_01") for i in ids)


def test_after_a_journal_failure_the_next_writes_are_not_attempted_until_the_pause_ends():
    rig = Rig()
    rig.audit.down = True
    feed(rig)
    rig.flush()
    first = rig.audit.attempts
    rig.advance(1)
    feed(rig, phases=plan(45, 25))
    rig.flush()
    assert rig.audit.attempts == first  # en pause : on n'insiste pas
