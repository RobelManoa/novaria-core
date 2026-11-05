"""Lecture d'un indicateur : fait prêt à écrire, ou rejet motivé."""

import pytest
import validate_events as ve

from app.flux.model import Rejection
from app.pipeline.facts import IndicatorFact, parse_indicator
from tests.unit.flux.support import epoch_ms, example

from .support import indicator, raw


def rejected(payload: bytes, **kwargs) -> Rejection:
    result = parse_indicator(payload, **kwargs)
    assert isinstance(result, Rejection), result
    return result


@pytest.mark.parametrize(
    "name",
    [
        "indicateur-congestion",
        "indicateur-fluide",
        "indicateur-route-vide",
        "indicateur-donnees-insuffisantes",
    ],
)
def test_lit_les_exemples_du_contrat(name):
    event = example(f"{name}.json")
    assert ve.validate_event(event) == []

    fact = parse_indicator(raw(event), key=b"INT_01", partition=1, offset=9)

    assert isinstance(fact, IndicatorFact)
    d = event["data"]
    assert (fact.event_id, fact.road_segment_id, fact.window_size_s) == (
        event["id"],
        d["road_segment_id"],
        d["window_size_s"],
    )
    assert fact.window_start_ms == epoch_ms(d["window_start"])
    assert (fact.vehicle_count, fact.flow_veh_per_min, fact.average_speed_kmh) == (
        d["vehicle_count"],
        d["flow_veh_per_min"],
        d["average_speed_kmh"],
    )
    assert (fact.occupancy_rate, fact.max_queue_length_m, fact.speed_ratio) == (
        d["occupancy_rate"],
        d["max_queue_length_m"],
        d["speed_ratio"],
    )
    assert (fact.sample_count, fact.expected_sample_count, fact.congestion_state) == (
        d["sample_count"],
        d["expected_sample_count"],
        d["congestion_state"],
    )
    assert fact.provenance == d["provenance"]
    assert (fact.partition, fact.offset) == (1, 9)


def test_la_fin_de_fenetre_suit_la_taille():
    fact = parse_indicator(raw(example("indicateur-fluide.json")))

    assert fact.window_end_ms - fact.window_start_ms == 60_000


@pytest.mark.parametrize("payload", [b"\xff\xfe", b"{pas du json", b'{"a": NaN}'])
def test_refuse_un_message_illisible(payload):
    assert rejected(payload).reason_code == "UNREADABLE"


def test_refuse_un_json_qui_n_est_pas_un_objet():
    assert rejected(b"[1]").reason_code == "CONTRACT_VIOLATION"


def test_refuse_une_mesure_sur_le_sujet_des_indicateurs():
    event = example("mesure-valide.json")

    result = rejected(raw(event))

    assert result.reason_code == "UNKNOWN_TYPE"
    assert result.intersection_id == "INT_01"


def test_refuse_un_indicateur_hors_contrat_sans_reprendre_la_valeur():
    event = indicator()
    event["data"]["vehicle_count"] = -987654

    result = rejected(raw(event))

    assert result.reason_code == "CONTRACT_VIOLATION"
    assert "987654" not in result.reason


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (lambda e: e.update(subject="INT_02"), "subject"),
        (lambda e: e.update(id="n-importe-quoi"), "id attendu"),
        (lambda e: e.update(time="2026-10-20T08:20:30Z"), "fin de la fenêtre"),
        (lambda e: e["data"].update(window_start="2026-10-20T08:20:10Z"), "aligné"),
        (lambda e: e["data"].update(sample_count=13, expected_sample_count=6), "double"),
    ],
)
def test_refuse_une_incoherence_entre_champs(change, fragment):
    event = indicator(name="indicateur-congestion.json")
    change(event)

    result = rejected(raw(event))

    assert result.reason_code == "SEMANTIC_VIOLATION"
    assert fragment in result.reason
