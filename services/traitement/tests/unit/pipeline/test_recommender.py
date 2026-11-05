"""Recommandations : quand, pour quel carrefour, quelles durées, jamais sur données douteuses."""

import dataclasses

import pytest
import validate_events as ve
from conformance import assert_publication

from app.pipeline.facts import IndicatorFact, parse_indicator
from app.pipeline.recommender import Recommender
from app.pipeline.reference import PlanReference, SegmentPlanInfo
from app.pipeline.webster import WebsterParams, webster_plan
from app.schemas.events import RecommendationEvent
from tests.unit.flux.support import epoch_ms

from .support import indicator, raw

T0 = epoch_ms("2026-10-20T08:00:00Z")
REFERENCE = PlanReference(
    {
        "ROAD_001": SegmentPlanInfo("ROAD_001", "INT_01", "N", 2),
        "ROAD_002": SegmentPlanInfo("ROAD_002", "INT_01", "E", 2),
        "ROAD_003": SegmentPlanInfo("ROAD_003", "INT_01", "S", 2),
        "ROAD_004": SegmentPlanInfo("ROAD_004", "INT_01", "W", 2),
        "ROAD_009": SegmentPlanInfo("ROAD_009", "INT_03", "N", 1),
        "ROAD_010": SegmentPlanInfo("ROAD_010", "INT_03", "S", 1),
    }
)
APPROACH_OF = {"ROAD_001": "N", "ROAD_002": "E", "ROAD_003": "S", "ROAD_004": "W"}


def fact(segment="ROAD_001", minute=0, state="FREE_FLOW", flow=10.0, run="r1") -> IndicatorFact:
    intersection = REFERENCE.segments[segment].intersection_id
    degraded = state in ("SLOW", "CONGESTED")
    event = indicator(
        segment=segment, intersection=intersection, start_ms=T0 + minute * 60_000, state=state,
        flow_veh_per_min=flow, run=run, speed_ratio=0.3 if degraded else 0.9,
        average_speed_kmh=15.0, vehicle_count=int(flow),
    )  # fmt: skip
    result = parse_indicator(raw(event), partition=0, offset=0)
    assert isinstance(result, IndicatorFact), result
    return result


def crossing(
    minute=0,
    states=("CONGESTED", "FREE_FLOW", "FREE_FLOW", "FREE_FLOW"),
    flows=(24, 15, 20, 18),
    run="r1",
):
    return [
        fact(seg, minute, st, fl, run)
        for seg, st, fl in zip(APPROACH_OF, states, flows, strict=True)
    ]


def test_une_approche_degradee_donne_la_recommandation_de_webster():
    events = Recommender(REFERENCE).feed(crossing())

    [event] = events
    data = event["data"]
    # N 24, S 20, E 15, W 18 véhicules par minute, deux voies : exemple résolu de test_webster.py
    assert data["cycle_s"] == 57
    assert [(p["phase_id"], p["green_approaches"], p["duration_s"]) for p in data["phases"]] == [
        ("P1", ["N", "S"], 32), ("P2", ["E", "W"], 25)]  # fmt: skip
    assert data["method"] == {"kind": "WEBSTER_REFERENCE", "version": "webster-v0"}
    assert data["model"] is None
    assert data["inputs"]["congestion_state"] == "CONGESTED"
    assert data["inputs"]["window_start"] == "2026-10-20T08:00:00Z"


def test_l_evenement_est_conforme_au_contrat_et_a_la_matrice_des_sujets():
    [event] = Recommender(REFERENCE).feed(crossing())

    assert ve.validate_event(event) == []
    assert RecommendationEvent.model_validate(event)
    assert_publication("traitement", "traffic.recommendations", event)


def test_l_evenement_porte_ses_indicateurs_sa_validite_et_sa_provenance():
    facts = crossing()
    [event] = Recommender(REFERENCE).feed(facts)

    assert event["data"]["inputs"]["indicator_ids"] == sorted(f.event_id for f in facts)
    assert event["time"] == "2026-10-20T08:01:00Z"  # fin de la fenêtre
    assert event["data"]["valid_until"] == "2026-10-20T08:06:00Z"  # cinq minutes plus tard
    assert event["data"]["provenance"] == facts[0].provenance
    assert event["subject"] == "INT_01" and event["id"] == event["data"]["recommendation_id"]


def test_l_identifiant_est_stable_et_propre_au_run_au_carrefour_et_a_la_fenetre():
    first = Recommender(REFERENCE).feed(crossing())[0]["id"]
    again = Recommender(REFERENCE).feed(crossing())[0]["id"]
    other_window = Recommender(REFERENCE).feed(crossing(minute=1))[0]["id"]
    other_run = Recommender(REFERENCE).feed(crossing(run="r2"))[0]["id"]

    assert first == again
    assert len({first, other_window, other_run}) == 3


def test_rien_tant_que_toutes_les_approches_ne_sont_pas_arrivees():
    recommender = Recommender(REFERENCE)

    assert recommender.feed(crossing()[:3]) == []
    assert len(recommender.feed(crossing()[3:])) == 1


def test_l_ordre_d_arrivee_ne_change_pas_la_recommandation():
    forward = Recommender(REFERENCE).feed(crossing())
    backward = Recommender(REFERENCE).feed(list(reversed(crossing())))

    assert forward == backward


def test_circulation_fluide_aucune_recommandation():
    recommender = Recommender(REFERENCE)

    assert recommender.feed(crossing(states=("FREE_FLOW",) * 4)) == []
    assert recommender.stats["no_need"] == 1


def test_une_approche_inconnue_empeche_la_recommandation():
    recommender = Recommender(REFERENCE)

    assert (
        recommender.feed(crossing(states=("CONGESTED", "UNKNOWN", "FREE_FLOW", "FREE_FLOW"))) == []
    )
    assert recommender.stats["unknown_approach"] == 1


def test_un_carrefour_a_un_seul_axe_ne_recoit_pas_de_plan():
    recommender = Recommender(REFERENCE)
    facts = [fact("ROAD_009", 0, "CONGESTED", 12), fact("ROAD_010", 0, "FREE_FLOW", 8)]

    assert recommender.feed(facts) == []
    assert recommender.stats["single_axis"] == 1


def test_une_fenetre_de_cinq_minutes_est_ignoree():
    five = [dataclasses.replace(f, window_size_s=300) for f in crossing()]  # carrefour complet

    assert Recommender(REFERENCE).feed(five) == []


def test_un_troncon_hors_reference_est_compte():
    recommender = Recommender(REFERENCE)
    stranger = fact("ROAD_001")
    stranger = dataclasses.replace(stranger, road_segment_id="ROAD_404")

    assert recommender.feed([stranger]) == []
    assert recommender.stats["unknown_segment"] == 1


def test_une_fenetre_plus_ancienne_restee_incomplete_est_abandonnee():
    recommender = Recommender(REFERENCE)
    recommender.feed(crossing(minute=0)[:2])  # la minute 0 n'aura jamais ses quatre approches

    events = recommender.feed(crossing(minute=1))

    assert len(events) == 1
    assert recommender.stats["incomplete_group"] == 1
    assert recommender.retained_offsets() == {}


def test_une_correction_tardive_ne_rouvre_pas_une_decision_prise():
    recommender = Recommender(REFERENCE)
    recommender.feed(crossing(minute=0))

    assert recommender.feed([fact("ROAD_001", 0, "CONGESTED", 30)]) == []
    assert recommender.stats["late_correction"] == 1


def test_les_runs_ne_se_melangent_pas():
    recommender = Recommender(REFERENCE)
    recommender.feed(crossing(run="a")[:2] + crossing(run="b")[2:])

    assert recommender.feed(crossing(run="a")[2:]) != []  # a est complet, b ne l'est pas


def test_les_offsets_attendus_restent_retenus():
    recommender = Recommender(REFERENCE)
    partial = [
        dataclasses.replace(f, partition=1, offset=40 + i) for i, f in enumerate(crossing()[:2])
    ]
    recommender.feed(partial)

    assert recommender.retained_offsets() == {1: 40}


@pytest.mark.parametrize("flows", [(24, 15, 20, 18), (18, 12, 18, 12), (3, 3, 3, 3)])
def test_les_durees_viennent_du_calcul_de_reference_pas_du_recommandeur(flows):
    [event] = Recommender(REFERENCE).feed(crossing(flows=flows))

    from fractions import Fraction

    from app.pipeline.webster import ApproachLoad

    loads = [ApproachLoad(a, Fraction(f), 2) for a, f in zip("NESW", flows, strict=True)]
    expected = webster_plan(loads, WebsterParams())
    assert event["data"]["cycle_s"] == expected.cycle_s
    assert [p["duration_s"] for p in event["data"]["phases"]] == [
        p.duration_s for p in expected.phases
    ]
