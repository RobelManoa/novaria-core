"""Plan de feux de référence (Webster) : déterministe, exemples résolus à la main (EXG-REP-01)."""

from fractions import Fraction

import pytest

from app.pipeline.webster import (
    VERSION,
    ApproachLoad,
    WebsterParams,
    webster_plan,
)

P = WebsterParams()


def loads(**veh_per_min):
    """`loads(N=24, S=20, E=15, W=18)` : deux voies par approche."""
    return [ApproachLoad(a, Fraction(flow), lanes=2) for a, flow in veh_per_min.items()]


def plan_of(plan):
    return [(p.phase_id, p.green_approaches, p.duration_s) for p in plan.phases]


def test_exemple_resolu_a_la_main():
    # y(N) = 24×60 ÷ (1800×2) = 0,4 ; y(S) = 0,3333 ; y(E) = 0,25 ; y(W) = 0,3
    # critiques : NS 0,4 et EW 0,3, donc Y = 0,7 ; perdu L = 2 phases × 4 s = 8 s
    # C = (1,5 × 8 + 5) ÷ (1 − 0,7) = 56,67, arrondi à 57 ; vert utile 57 − 8 = 49
    # vert NS = 49 × 0,4 ÷ 0,7 = 28 ; vert EW = 21 ; durée de phase = vert + 4 s perdues
    plan = webster_plan(loads(N=24, S=20, E=15, W=18), P)

    assert plan.cycle_s == 57
    assert plan_of(plan) == [("P1", ("N", "S"), 32), ("P2", ("E", "W"), 25)]


def test_le_cycle_est_la_somme_des_phases():
    plan = webster_plan(loads(N=24, S=20, E=15, W=18), P)

    assert plan.cycle_s == sum(p.duration_s for p in plan.phases)


def test_peu_de_circulation_le_cycle_ne_descend_pas_sous_le_minimum():
    plan = webster_plan(loads(N=3, S=3, E=3, W=3), P)  # C = 17 ÷ (1 − 0,1) = 18,9 -> 30

    assert plan.cycle_s == 30


def test_sans_aucun_flux_les_phases_sont_egales():
    plan = webster_plan(loads(N=0, S=0, E=0, W=0), P)

    assert plan.cycle_s == 30
    assert [p.duration_s for p in plan.phases] == [15, 15]  # vert utile 22 : 11 et 11, plus 4 s


def test_une_circulation_saturee_est_plafonnee_au_cycle_maximal():
    plan = webster_plan(loads(N=60, S=60, E=50, W=50), P)  # Y = 1,0 + 0,83 > 0,9

    assert plan.cycle_s == 120
    assert plan.flow_ratio > Fraction(9, 10)


def test_une_phase_ne_descend_pas_sous_le_vert_minimal():
    # y(NS) = 33×60÷3600 = 0,55 ; y(EW) = 1,2×60÷3600 = 0,02 ; Y = 0,57 ; C = 17 ÷ 0,43 = 39,5 -> 40
    # vert utile 32 : proportionnel 30,9 et 1,1 ; l'est-ouest passe au minimum de 6 s
    plan = webster_plan(
        [ApproachLoad("N", Fraction(33), 2), ApproachLoad("E", Fraction(6, 5), 2)], P
    )

    assert plan.cycle_s == 40
    assert plan_of(plan) == [("P1", ("N",), 30), ("P2", ("E",), 10)]


def test_un_carrefour_a_trois_approches_a_deux_phases():
    plan = webster_plan(loads(N=24, S=20, E=15), P)

    assert [p.green_approaches for p in plan.phases] == [("N", "S"), ("E",)]


def test_une_seule_voie_double_la_charge_par_voie():
    two = webster_plan([ApproachLoad("N", Fraction(20), 2), ApproachLoad("E", Fraction(20), 2)], P)
    one = webster_plan([ApproachLoad("N", Fraction(20), 1), ApproachLoad("E", Fraction(20), 1)], P)

    assert one.cycle_s > two.cycle_s  # y double : Y 0,667 contre 0,333


def test_un_seul_axe_ne_donne_pas_de_plan():
    assert webster_plan(loads(N=24, S=20), P) is None
    assert webster_plan([], P) is None


def test_la_version_de_la_methode_est_nommee():
    assert VERSION == "webster-v0"


def test_le_resultat_ne_depend_que_des_entrees():
    first = webster_plan(loads(N=24, S=20, E=15, W=18), P)
    second = webster_plan(loads(W=18, E=15, S=20, N=24), P)  # ordre d'arrivée différent

    assert first == second


@pytest.mark.parametrize(
    ("flows", "expected_cycle"),
    [
        ({"N": 10, "S": 8, "E": 6, "W": 7}, 30),  # Y = 0,28 : C0 = 23,7, minimum 30
        ({"N": 20, "S": 18, "E": 16, "W": 12}, 43),  # Y = 0,6 : C0 = 42,5, vers le haut
        ({"N": 30, "S": 22, "E": 20, "W": 25}, 120),  # Y > 0,9 : plafond
    ],
)
def test_le_cycle_egale_la_formule_calculee_a_part(flows, expected_cycle):
    """Recalcul indépendant en flottants, sans fractions ni aucune fonction du module."""
    y = {a: q * 60 / (1800 * 2) for a, q in flows.items()}
    critical = [max(y[a] for a in axis if a in y) for axis in (("N", "S"), ("E", "W"))]
    capped = min(sum(critical), 0.9)
    c0 = (1.5 * 8 + 5) / (1 - capped)
    reference = min(120, max(30, int(c0 + 0.5)))

    assert reference == expected_cycle
    assert webster_plan(loads(**flows), P).cycle_s == reference


def test_les_unites_restantes_vont_aux_plus_forts_restes():
    # y(NS) = 0,3 ; y(EW) = 0,2 ; Y = 0,5 ; C = 17 ÷ 0,5 = 34 ; vert utile 26
    # parts exactes 15,6 et 10,4 : le reste de 0,6 l'emporte sur 0,4 : 16 et 10 (et non 15 et 11)
    plan = webster_plan(loads(N=18, S=18, E=12, W=12), P)

    assert plan.cycle_s == 34
    assert plan_of(plan) == [("P1", ("N", "S"), 20), ("P2", ("E", "W"), 14)]


def test_le_cycle_laisse_au_moins_le_vert_minimal_et_le_temps_perdu_de_chaque_phase():
    # sans flux, C0 = 17 s ; minimum de cycle 10 s ; mais 2 × (6 s de vert + 4 s perdues) = 20 s
    short = WebsterParams(min_cycle_s=10, min_green_s=6)

    plan = webster_plan(loads(N=0, S=0, E=0, W=0), short)

    assert plan.cycle_s == 20
    assert [p.duration_s for p in plan.phases] == [10, 10]
