"""Garde-fous (EXG-REP-02) : pour chaque règle, un plan ou une durée qui la viole est refusé."""

import pytest

from app.domain import safety
from app.domain.safety import DEFAULT_LAYOUT, Phase, check_duration, check_plan, validate_layout
from tests.support import plan


def codes(phases, cycle=None):
    total = sum(p.duration_s for p in phases) if cycle is None else cycle
    return [v.code for v in check_plan(phases, total, DEFAULT_LAYOUT)]


def test_a_plan_with_the_layout_of_the_intersection_and_bounded_durations_is_safe():
    assert codes(plan(40, 20)) == []
    assert codes(plan(safety.MIN_PHASE_S, 20)) == []  # le minimum est permis
    assert codes(plan(safety.MAX_PHASE_S, 30)) == []  # le maximum aussi


@pytest.mark.parametrize(
    "approaches",
    [("N", "E"), ("N", "W"), ("S", "E"), ("S", "W"), ("N", "S", "E"), ("N", "E", "S", "W")],
)
def test_two_crossing_approaches_are_never_green_together(approaches):
    bad = [Phase("P1", approaches, 30), Phase("P2", ("E", "W"), 30)]
    found = codes(bad)
    assert found[0] == "CONFLICTING_GREENS"  # le plus grave d'abord


@pytest.mark.parametrize("approaches", [("N", "S"), ("E", "W"), ("N",), ("W",)])
def test_approaches_of_the_same_axis_may_be_green_together(approaches):
    assert safety.conflicting_pairs(approaches) == []


def test_the_phases_must_be_those_of_the_intersection():
    swapped = [Phase("P1", ("E", "W"), 30), Phase("P2", ("N", "S"), 30)]
    reordered = [Phase("P2", ("E", "W"), 30), Phase("P1", ("N", "S"), 30)]
    only_one = [Phase("P1", ("N", "S"), 60)]
    unknown = [Phase("P1", ("N", "S"), 30), Phase("P3", ("E", "W"), 30)]
    for bad in (swapped, reordered, only_one, unknown):
        assert "PHASE_LAYOUT_MISMATCH" in codes(bad)


@pytest.mark.parametrize(
    ("p1", "expected"),
    [(safety.MIN_PHASE_S - 1, "PHASE_TOO_SHORT"), (safety.MAX_PHASE_S + 1, "PHASE_TOO_LONG")],
)
def test_a_phase_outside_its_bounds_is_refused(p1, expected):
    assert expected in codes(plan(p1, 30))


def test_the_cycle_is_the_sum_of_the_phases_and_stays_within_bounds():
    assert "CYCLE_MISMATCH" in codes(plan(30, 30), cycle=70)
    assert "CYCLE_OUT_OF_BOUNDS" in codes(plan(12, 12))  # 24 s : sous le minimum
    assert "CYCLE_OUT_OF_BOUNDS" in codes(plan(90, 40))  # 130 s : au-dessus du maximum


def test_all_the_defects_are_reported_the_most_serious_first():
    bad = [Phase("P1", ("N", "E"), 5), Phase("P2", ("E", "W"), 200)]
    found = codes(bad, cycle=50)
    assert found[0] == "CONFLICTING_GREENS"
    assert {"PHASE_TOO_SHORT", "PHASE_TOO_LONG", "CYCLE_MISMATCH", "CYCLE_OUT_OF_BOUNDS"} <= set(
        found
    )


@pytest.mark.parametrize(
    ("duration", "code"), [(9, "PHASE_TOO_SHORT"), (10, None), (90, None), (91, "PHASE_TOO_LONG")]
)
def test_the_duration_limits_are_inclusive(duration, code):
    result = check_duration(duration)
    assert (result.code if result else None) == code


@pytest.mark.parametrize(
    "layout",
    [
        (("P1", ("N", "S")),),  # une seule phase
        (("P1", ("N", "S")), ("P1", ("E", "W"))),  # identifiants en double
        (("P1", ("N", "E")), ("P2", ("S", "W"))),  # vert conflictuel
        (("P1", ("N", "S")), ("P2", ("E",))),  # l'approche W n'est jamais servie
        (("P1", ()), ("P2", ("E", "W"))),  # phase vide
        (("P1", ("N", "S")), ("P2", ("E", "X"))),  # approche inconnue
    ],
)
def test_a_dangerous_layout_is_refused_at_startup(layout):
    with pytest.raises(ValueError):
        validate_layout(layout)


def test_the_default_layout_is_itself_safe():
    validate_layout(DEFAULT_LAYOUT)
