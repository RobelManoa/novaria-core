"""Contrôleur de feux simulé : phases, dégagements, modes, commandes et retour au plan fixe."""

import random
from datetime import timedelta

import pytest

from app.domain.model import Mode, Origin, Outcome
from app.domain.safety import ALL_RED_S, CONFLICTS, MIN_PHASE_S, Phase
from tests.support import at, new_controller, plan, recommend, resume, set_phase


def state(controller, now):
    return controller.view(at(now))


# --------------------------------------------------------------------------- le cycle
def test_at_startup_the_fixed_plan_runs_in_degraded_mode_from_the_first_phase():
    view = state(new_controller(), 0)
    assert (view.mode, view.phase_id, view.signal) == (Mode.DEGRADED_FIXED_PLAN, "P1", "GREEN")
    assert view.green_approaches == ("N", "S")
    assert [p.duration_s for p in view.phases] == [30, 30]
    assert (view.decision.origin, view.decision.outcome) == (Origin.STARTUP, Outcome.APPLIED)


def test_each_phase_ends_with_an_all_red_clearance_before_the_next_one_turns_green():
    controller = new_controller()
    controller.tick(at(10))
    assert state(controller, 25).signal == "GREEN"
    cleared = state(controller, 26)  # 30 - ALL_RED_S
    assert (cleared.signal, cleared.green_approaches) == ("ALL_RED", ())
    controller.tick(at(30))
    nxt = state(controller, 30)
    assert (nxt.phase_id, nxt.signal, nxt.green_approaches) == ("P2", "GREEN", ("E", "W"))


def test_the_cycle_wraps_after_the_last_phase():
    controller = new_controller()
    controller.tick(at(65))
    assert state(controller, 65).phase_id == "P1"
    assert state(controller, 65).phase_started_at == at(60)


def test_a_long_gap_catches_up_phase_by_phase_without_skipping_the_schedule():
    controller = new_controller()
    controller.tick(at(10_000))  # le service n'a pas tourné : le calendrier reprend où il en serait
    view = state(controller, 10_000)
    assert view.phase_started_at == at(9_990)  # 10 000 = 166 cycles de 60 s + 40 ; P2 depuis 9 990


# --------------------------------------------------------------------------- recommandations
def test_a_safe_recommendation_switches_to_automatic_and_changes_the_durations():
    controller = new_controller()
    decision = recommend(controller, 5)
    assert decision.outcome is Outcome.APPLIED and decision.origin is Origin.RECOMMENDATION
    view = state(controller, 5)
    assert view.mode is Mode.AUTOMATIC
    assert [p.duration_s for p in view.phases] == [40, 20]
    assert view.phase_ends_at == at(40)  # la phase en cours prend la nouvelle durée


def test_a_recommendation_never_cuts_the_running_phase_below_its_minimum_or_its_clearance():
    controller = new_controller()
    controller.tick(at(12))
    recommend(controller, 12, plan(MIN_PHASE_S, 20))  # P1 vaut 10 s mais en dure déjà 12
    assert state(controller, 12).phase_ends_at == at(12 + ALL_RED_S)


def test_a_recommendation_cannot_shorten_a_phase_before_its_minimum_has_elapsed():
    controller = new_controller()
    recommend(controller, 2, plan(MIN_PHASE_S, 20))
    assert state(controller, 2).phase_ends_at == at(MIN_PHASE_S)


def test_a_recommendation_does_not_touch_a_phase_already_in_its_clearance():
    controller = new_controller()
    controller.tick(at(27))
    recommend(controller, 27, plan(60, 20))
    assert state(controller, 27).phase_ends_at == at(30)


@pytest.mark.parametrize(
    "phases",
    [
        [Phase("P1", ("N", "E"), 30), Phase("P2", ("S", "W"), 30)],  # verts conflictuels
        plan(5, 40),  # trop courte
        plan(95, 20),  # trop longue
    ],
)
def test_a_dangerous_recommendation_is_refused_and_changes_nothing(phases):
    controller = new_controller()
    decision = recommend(controller, 5, phases)
    assert decision.outcome is Outcome.REFUSED and not decision.changed
    view = state(controller, 5)
    assert view.mode is Mode.DEGRADED_FIXED_PLAN
    assert [p.duration_s for p in view.phases] == [30, 30]
    assert view.phase_ends_at == at(30)


def test_a_refused_recommendation_keeps_the_previous_good_plan():
    controller = new_controller()
    recommend(controller, 1)
    refused = recommend(controller, 2, plan(5, 5))
    assert refused.refused
    view = state(controller, 2)
    assert view.mode is Mode.AUTOMATIC and [p.duration_s for p in view.phases] == [40, 20]


def test_the_first_violation_is_the_reason_and_all_are_listed():
    bad = [Phase("P1", ("N", "E"), 5), Phase("P2", ("E", "W"), 30)]
    decision = recommend(new_controller(), 1, bad)
    assert decision.refusal_reason == "CONFLICTING_GREENS"
    assert decision.reasons == ("CONFLICTING_GREENS", "PHASE_LAYOUT_MISMATCH", "PHASE_TOO_SHORT")
    assert "se croisent" in decision.detail and "minimum" in decision.detail


def test_a_replayed_older_or_expired_recommendation_is_ignored():
    controller = new_controller()
    first = recommend(controller, 10)
    assert first is not None
    replay = controller.on_recommendation(
        first.reference_id, at(20), plan(), 60, 300, controller.provenance, at(20)
    )
    assert replay is None  # même identifiant : rejouée
    assert recommend(controller, 30, sequence=5) is None  # plus ancienne que la dernière reçue
    assert recommend(controller, 40, validity=0) is None  # déjà périmée
    assert recommend(controller, 50, validity=-1) is None


# --------------------------------------------------------------------------- mode dégradé
def test_without_new_recommendations_the_controller_returns_to_the_fixed_plan():
    controller = new_controller(max_silence_s=600)
    recommend(controller, 0, validity=120)
    assert controller.tick(at(119)) == [] and state(controller, 119).mode is Mode.AUTOMATIC
    fell = controller.tick(at(120))
    assert [d.origin for d in fell] == [Origin.FIXED_PLAN_FALLBACK]
    view = state(controller, 120)
    assert view.mode is Mode.DEGRADED_FIXED_PLAN and [p.duration_s for p in view.phases] == [30, 30]


def test_silence_is_capped_even_if_the_recommendation_claims_a_long_validity():
    controller = new_controller(max_silence_s=180)
    recommend(controller, 0, validity=3600)
    assert controller.tick(at(179)) == []
    assert [d.origin for d in controller.tick(at(180))] == [Origin.FIXED_PLAN_FALLBACK]


def test_a_new_recommendation_renews_the_deadline_and_the_fallback_is_reported_once():
    controller = new_controller(max_silence_s=100)
    recommend(controller, 0)
    recommend(controller, 90)
    assert controller.tick(at(150)) == []  # le délai est reparti de 90
    assert len(controller.tick(at(190))) == 1
    assert controller.tick(at(200)) == []  # déjà revenu : rien de plus à dire


def test_normal_operation_resumes_at_the_next_recommendation():
    controller = new_controller(max_silence_s=100)
    recommend(controller, 0)
    controller.tick(at(100))
    assert recommend(controller, 105).outcome is Outcome.APPLIED
    assert state(controller, 105).mode is Mode.AUTOMATIC


def test_the_fallback_does_not_cut_the_running_phase_below_its_minimum():
    controller = new_controller(max_silence_s=100)
    recommend(controller, 0, plan(90, 20))  # P1 dure 90 s
    controller.tick(at(100))  # P1 (90 s) est finie : P2 tourne depuis 94
    assert state(controller, 100).phase_id == "P2"
    assert state(controller, 100).phase_ends_at >= at(94 + MIN_PHASE_S)


# --------------------------------------------------------------------------- commande manuelle
def test_a_manual_phase_is_reached_through_a_clearance_and_held_for_its_duration():
    controller = new_controller()
    controller.tick(at(12))
    decision = controller.on_command(set_phase("P2", 30), at(12))
    assert decision.outcome is Outcome.APPLIED and decision.origin is Origin.MANUAL_COMMAND
    assert state(controller, 12).mode is Mode.MANUAL
    assert state(controller, 12).signal == "ALL_RED"  # le vert en cours s'arrête : dégagement
    assert state(controller, 15).green_approaches == ()
    controller.tick(at(12 + ALL_RED_S))
    assert state(controller, 16).phase_id == "P2" and state(controller, 16).green_approaches == (
        "E",
        "W",
    )
    assert state(controller, 16).phase_ends_at == at(46)


def test_the_manual_hold_overrides_the_automatic_plan_then_hands_back_to_it_if_still_valid():
    controller = new_controller()
    recommend(controller, 0)
    controller.tick(at(12))
    assert controller.on_command(set_phase("P2", 20), at(12)).outcome is Outcome.APPLIED
    ended = controller.tick(at(36))  # tenue de 16 à 36
    assert [(d.origin, d.outcome) for d in ended] == [(Origin.MANUAL_COMMAND, Outcome.APPLIED)]
    assert state(controller, 36).mode is Mode.AUTOMATIC


def test_the_manual_hold_ends_in_the_fixed_plan_when_the_recommendations_have_gone():
    controller = new_controller(max_silence_s=30)
    recommend(controller, 0)
    controller.tick(at(12))
    controller.on_command(set_phase("P2", 60), at(12))
    assert controller.tick(at(40)) == []  # la péremption pendant la tenue ne change rien
    assert state(controller, 40).mode is Mode.MANUAL
    ended = controller.tick(at(76))
    assert [d.origin for d in ended] == [Origin.FIXED_PLAN_FALLBACK]
    assert state(controller, 76).mode is Mode.DEGRADED_FIXED_PLAN


def test_a_second_manual_command_while_one_is_running_is_refused():
    controller = new_controller()
    controller.tick(at(12))
    controller.on_command(set_phase("P2", 30), at(12))
    again = controller.on_command(set_phase("P1", 30), at(20))
    assert again.refusal_reason == "COMMAND_IN_PROGRESS" and not again.changed
    assert (
        controller.on_command(set_phase("P2", 30), at(20)).refusal_reason == "COMMAND_IN_PROGRESS"
    )


def test_a_command_before_the_running_phase_has_lasted_its_minimum_is_refused():
    controller = new_controller()
    decision = controller.on_command(set_phase("P2", 30), at(MIN_PHASE_S - 1))
    assert decision.refusal_reason == "MIN_DURATION_NOT_ELAPSED"
    assert state(controller, 5).mode is Mode.DEGRADED_FIXED_PLAN  # rien n'a changé
    assert controller.on_command(set_phase("P2", 30), at(MIN_PHASE_S)).outcome is Outcome.APPLIED


def test_a_command_during_a_clearance_is_refused():
    controller = new_controller()
    decision = controller.on_command(set_phase("P2", 30), at(27))
    assert decision.refusal_reason == "CLEARANCE_IN_PROGRESS"


@pytest.mark.parametrize(
    ("phase", "duration", "reason"),
    [
        ("P2", 9, "PHASE_TOO_SHORT"),
        ("P2", 91, "PHASE_TOO_LONG"),
        ("P9", 30, "UNKNOWN_PHASE"),
        ("P2", None, "PHASE_TOO_SHORT"),
    ],
)
def test_a_dangerous_manual_command_is_refused_and_the_state_is_unchanged(phase, duration, reason):
    controller = new_controller()
    controller.tick(at(12))
    before = state(controller, 12)
    decision = controller.on_command(set_phase(phase, duration), at(12))
    assert decision.refusal_reason == reason and decision.outcome is Outcome.REFUSED
    assert state(controller, 12) == before


def test_holding_the_current_phase_extends_it_without_a_clearance():
    controller = new_controller()
    controller.tick(at(5))
    assert controller.on_command(set_phase("P1", 50), at(5)).outcome is Outcome.APPLIED
    view = state(controller, 5)
    assert (view.mode, view.phase_id, view.phase_ends_at) == (Mode.MANUAL, "P1", at(55))


def test_a_recommendation_during_a_manual_command_is_refused_and_the_command_prevails():
    controller = new_controller()
    controller.tick(at(12))
    controller.on_command(set_phase("P2", 30), at(12))
    decision = recommend(controller, 20)
    assert decision.refusal_reason == "MANUAL_OVERRIDE"
    assert state(controller, 20).mode is Mode.MANUAL


def test_resuming_automatic_ends_the_hold_after_a_clearance():
    controller = new_controller()
    recommend(controller, 0)
    controller.tick(at(12))
    controller.on_command(set_phase("P2", 60), at(12))
    controller.tick(at(16))
    decision = controller.on_command(resume(), at(30))  # P2 dure depuis 14 s
    assert decision.outcome is Outcome.APPLIED and decision.changed
    view = state(controller, 30)
    assert view.mode is Mode.AUTOMATIC and view.phase_ends_at == at(30 + ALL_RED_S)
    controller.tick(at(34))
    assert state(controller, 34).phase_id == "P1"


def test_resuming_without_recommendation_goes_to_the_fixed_plan():
    controller = new_controller()
    controller.tick(at(12))
    controller.on_command(set_phase("P2", 60), at(12))
    controller.tick(at(30))
    controller.on_command(resume(), at(30))
    assert state(controller, 30).mode is Mode.DEGRADED_FIXED_PLAN


def test_resuming_too_early_or_during_the_forced_clearance_is_refused():
    controller = new_controller()
    controller.tick(at(12))
    controller.on_command(set_phase("P2", 60), at(12))
    assert controller.on_command(resume(), at(14)).refusal_reason == "CLEARANCE_IN_PROGRESS"
    controller.tick(at(16))
    assert controller.on_command(resume(), at(20)).refusal_reason == "MIN_DURATION_NOT_ELAPSED"
    assert state(controller, 20).mode is Mode.MANUAL


def test_resuming_during_the_clearance_of_the_held_phase_simply_releases_the_hold():
    controller = new_controller()
    controller.tick(at(12))
    controller.on_command(set_phase("P1", 20), at(12))  # P1 tenue jusqu'à 32 (dégagement dès 28)
    decision = controller.on_command(resume(), at(29))
    assert decision.changed and state(controller, 29).mode is Mode.DEGRADED_FIXED_PLAN
    assert state(controller, 29).phase_ends_at == at(32)


def test_resuming_with_nothing_to_resume_changes_nothing():
    controller = new_controller()
    decision = controller.on_command(resume(), at(5))
    assert decision.outcome is Outcome.APPLIED and not decision.changed


# --------------------------------------------------------------------------- invariants
def test_whatever_happens_the_signals_stay_safe():
    """Mille séquences aléatoires de recommandations, de commandes et d'attente.

    Invariants, vérifiés chaque seconde : jamais deux approches qui se croisent au vert ; un
    changement de phase est toujours précédé d'un dégagement ; aucune phase ne finit avant
    `MIN_PHASE_S`.
    """
    rng = random.Random(2026)  # noqa: S311 - séquences reproductibles, rien de cryptographique
    for _ in range(1000):
        controller = new_controller(
            fixed_s=rng.choice([10, 30, 90]), max_silence_s=rng.choice([20, 60, 180])
        )
        previous = state(controller, 0)
        started = {"phase": previous.phase_id, "at": previous.phase_started_at}
        for second in range(1, 400):
            now = at(second)
            controller.tick(now)
            roll = rng.random()
            if roll < 0.05:
                p1, p2 = rng.randint(1, 100), rng.randint(1, 100)
                recommend(controller, second, plan(p1, p2), validity=rng.choice([30, 120, 300]))
            elif roll < 0.10:
                controller.on_command(
                    set_phase(rng.choice(["P1", "P2", "P9"]), rng.randint(1, 100)), now
                )
            elif roll < 0.12:
                controller.on_command(resume(), now)
            view = state(controller, second)
            greens = view.green_approaches
            assert not any(frozenset((a, b)) in CONFLICTS for a in greens for b in greens)
            if view.phase_started_at != started["at"]:
                assert previous.signal == "ALL_RED", "changement de phase sans dégagement"
                lasted = (view.phase_started_at - started["at"]).total_seconds()
                assert lasted >= MIN_PHASE_S, f"phase de {lasted} s"
                started = {"phase": view.phase_id, "at": view.phase_started_at}
            previous = view
    assert timedelta(seconds=ALL_RED_S).total_seconds() == ALL_RED_S


# --------------------------------------------------------------------------- limites exactes
def test_the_clearance_starts_exactly_four_seconds_before_the_end_of_the_phase():
    controller = new_controller()
    assert state(controller, 25.999).signal == "GREEN"
    assert state(controller, 26).signal == "ALL_RED"
    assert (
        controller.on_command(set_phase("P2", 30), at(26)).refusal_reason == "CLEARANCE_IN_PROGRESS"
    )
    assert controller.on_command(set_phase("P2", 30), at(25.5)).outcome is Outcome.APPLIED


def test_two_recommendations_with_the_same_instant_are_not_both_applied():
    controller = new_controller()
    assert recommend(controller, 10, sequence=10) is not None
    assert recommend(controller, 11, plan(50, 30), sequence=10) is None  # même instant : ignorée
    assert [p.duration_s for p in state(controller, 11).phases] == [40, 20]


def test_stopping_releases_the_manual_hold_so_that_the_next_command_is_accepted():
    controller = new_controller()
    controller.tick(at(12))
    controller.on_command(set_phase("P2", 60), at(12))
    controller.stop(at(13))
    controller.tick(at(40))
    assert controller.hold_command is None and controller.forced is None
    reasons = []
    for second in range(41, 130):  # une fois la phase assez ancienne, la commande passe
        controller.tick(at(second))
        decision = controller.on_command(set_phase("P1", 20), at(second))
        reasons.append(decision.refusal_reason)
        if not decision.refused:
            break
    assert "COMMAND_IN_PROGRESS" not in reasons and not decision.refused
