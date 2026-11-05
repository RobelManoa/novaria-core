"""De la fenêtre à l'événement `novaria.traffic.indicator.v1` : valeurs, arrondis, contrat."""

from decimal import Decimal

import pytest
import validate_events as ve
from conformance import assert_publication

from app.flux.indicators import Indicator, Withheld, build, completeness, observation, speed_ratio
from app.flux.model import Measurement, Referential, SegmentRef, SensorRef
from app.flux.windows import Window
from app.schemas.events import IndicatorEvent

from .support import epoch_ms, example

REF = Referential(
    sensors={
        "SENSOR_001": SensorRef("SENSOR_001", "ROAD_001", "INT_01", 10),
        "SENSOR_005": SensorRef("SENSOR_005", "ROAD_005", "INT_02", 10),
        "SENSOR_009": SensorRef("SENSOR_009", "ROAD_009", "INT_03", 10),
        "SENSOR_010": SensorRef("SENSOR_010", "ROAD_010", "INT_03", 10),
        "SENSOR_011": SensorRef("SENSOR_011", "ROAD_010", "INT_03", 20),
    },
    segments={
        "ROAD_001": SegmentRef("ROAD_001", 1, "INT_01", 50.0),
        "ROAD_005": SegmentRef("ROAD_005", 5, "INT_02", 50.0),
        "ROAD_009": SegmentRef("ROAD_009", 9, "INT_03", 50.0),
        "ROAD_010": SegmentRef("ROAD_010", 10, "INT_03", 10.0),
    },
)
PROVENANCE = {
    "source_type": "SIMULATED",
    "run_id": "run-demo-0001",
    "scenario_id": "heure-de-pointe",
    "seed": 42,
}


def window(road, inter, start, rows, size=60, sensor="SENSOR_001") -> Window:
    """Une fenêtre de mesures de 10 s : rows = (véhicules, vitesse, occupation, file)."""
    w = Window("run-demo-0001", road, inter, size, epoch_ms(start), PROVENANCE)
    for index, (count, speed, occupancy, queue) in enumerate(rows):
        time_ms = w.start_ms + (index + 1) * 10_000
        w.add(
            Measurement(
                id=f"x:{index}",
                run_id="run-demo-0001",
                source_type="SIMULATED",
                scenario_id="heure-de-pointe",
                seed=42,
                dataset_id=None,
                sensor_id=sensor,
                road_segment_id=road,
                intersection_id=inter,
                time_ms=time_ms,
                interval_s=10,
                vehicle_count=count,
                speed_kmh=speed,
                occupancy_rate=occupancy,
                queue_length_m=queue,
                status="VALID",
                flags=(),
                correlation_id=None,
            )
        )
    return w


def built(w, state, ref=REF) -> Indicator:
    result = build(w, ref, state)
    assert isinstance(result, Indicator), result
    return result


# ------------------------------------------------------------ les quatre exemples du contrat


def test_reproduit_l_exemple_congestionne():
    w = window(
        "ROAD_001",
        "INT_01",
        "2026-10-20T08:20:00Z",
        [(1, 11.4, 0.78, 140.0)] * 3 + [(2, 11.4, 0.78, 140.0)] * 3,
    )

    assert built(w, "CONGESTED").event == example("indicateur-congestion.json")


def test_reproduit_l_exemple_fluide():
    w = window(
        "ROAD_001",
        "INT_01",
        "2026-10-20T08:00:00Z",
        [(4, 47.5, 0.12, 15.0)] * 4 + [(3, 47.5, 0.12, 15.0)] * 2,
    )

    assert built(w, "FREE_FLOW").event == example("indicateur-fluide.json")


def test_reproduit_l_exemple_de_route_vide():
    w = window(
        "ROAD_005", "INT_02", "2026-10-20T03:00:00Z", [(0, None, 0.0, 0.0)] * 6, sensor="SENSOR_005"
    )

    assert built(w, "FREE_FLOW").event == example("indicateur-route-vide.json")


def test_reproduit_l_exemple_de_donnees_insuffisantes():
    w = window(
        "ROAD_009",
        "INT_03",
        "2026-10-20T08:00:00Z",
        [(1, 30.0, None, None)] * 2,
        sensor="SENSOR_009",
    )
    ref_six = Referential(REF.sensors, REF.segments)

    assert built(w, "UNKNOWN", ref_six).event == example("indicateur-donnees-insuffisantes.json")


@pytest.mark.parametrize(
    "name",
    [
        "indicateur-congestion",
        "indicateur-fluide",
        "indicateur-route-vide",
        "indicateur-donnees-insuffisantes",
    ],
)
def test_les_exemples_reproduits_sont_conformes_au_contrat(name):
    event = example(f"{name}.json")

    assert ve.validate_event(event) == []
    assert IndicatorEvent.model_validate(event)


# --------------------------------------------------------------------------------- calculs


def test_le_debit_est_rapporte_a_la_minute():
    one = built(
        window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(10, 40.0, 0.2, 0.0)] * 6),
        "FREE_FLOW",
    )
    five = built(
        window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(10, 40.0, 0.2, 0.0)] * 6, size=300),
        "FREE_FLOW",
    )

    assert one.event["data"]["flow_veh_per_min"] == 60.0
    assert five.event["data"]["flow_veh_per_min"] == 12.0  # 60 véhicules en 5 minutes
    assert five.event["data"]["expected_sample_count"] == 30
    assert five.event["id"] == "run-demo-0001:ROAD_001:300:1792483200000"
    assert five.event["time"] == "2026-10-20T08:05:00Z"


def test_l_attendu_somme_les_capteurs_du_troncon():
    # ROAD_010 : un capteur toutes les 10 s (6) et un toutes les 20 s (3) par minute
    w = window(
        "ROAD_010", "INT_03", "2026-10-20T08:00:00Z", [(1, 5.0, 0.1, 0.0)] * 3, sensor="SENSOR_010"
    )

    assert built(w, "UNKNOWN").event["data"]["expected_sample_count"] == 9
    assert completeness(w, REF) == pytest.approx(3 / 9)


def test_la_completude_est_plafonnee_a_un():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(1, 40.0, 0.1, 0.0)] * 9)

    assert completeness(w, REF) == 1.0


def test_le_ratio_est_la_vitesse_sur_la_vitesse_fluide_arrondie_au_millieme():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(3, 33.3333, 0.2, 0.0)] * 6)

    assert speed_ratio(w, REF) == pytest.approx(33.3333 / 50, abs=0.0005)
    assert built(w, "SLOW").event["data"]["speed_ratio"] == round(33.3333 / 50, 3)


def test_le_ratio_est_plafonne_a_9_999():
    w = window(
        "ROAD_010",
        "INT_03",
        "2026-10-20T08:00:00Z",
        [(2, 200.0, 0.2, 0.0)] * 6,
        sensor="SENSOR_010",
    )

    assert speed_ratio(w, REF) == 9.999


def test_pas_de_ratio_sans_vitesse():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(0, None, 0.0, 0.0)] * 6)

    assert speed_ratio(w, REF) is None


def test_l_observation_reprend_completude_ratio_et_vehicules():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(5, 25.0, 0.3, 0.0)] * 3)

    obs = observation(w, REF)

    assert (obs.start_ms, obs.completeness, obs.speed_ratio, obs.vehicle_count) == (
        w.start_ms,
        0.5,
        0.5,
        15,
    )


def test_la_correction_tardive_garde_l_identifiant():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(4, 40.0, 0.2, 0.0)] * 5)
    first = built(w, "FREE_FLOW")
    w.add(
        Measurement(
            id="x:late",
            run_id="run-demo-0001",
            source_type="SIMULATED",
            scenario_id=None,
            seed=None,
            dataset_id=None,
            sensor_id="SENSOR_001",
            road_segment_id="ROAD_001",
            intersection_id="INT_01",
            time_ms=w.start_ms + 60_000,
            interval_s=10,
            vehicle_count=4,
            speed_kmh=40.0,
            occupancy_rate=0.2,
            queue_length_m=0.0,
            status="VALID",
            flags=(),
            correlation_id=None,
        )
    )
    second = built(w, "FREE_FLOW")

    assert first.key == second.key == first.event["id"]
    assert first.event["data"]["sample_count"] == 5 and second.event["data"]["sample_count"] == 6
    assert second.event["data"]["vehicle_count"] == 24


def test_les_evenements_produits_passent_le_controle_de_conformite_du_service():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(4, 40.0, 0.2, 5.0)] * 6)

    assert_publication("traitement", "traffic.indicators", built(w, "FREE_FLOW").event)


# ----------------------------------------------------------------------------- à retenir


def test_un_etat_degrade_sans_ratio_est_retenu_et_non_publie():
    # route vide pendant une congestion encore confirmée : le contrat exige un ratio, aucun inventé
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(0, None, 0.0, 0.0)] * 6)

    result = build(w, REF, "CONGESTED")

    assert isinstance(result, Withheld)
    assert result.reason_code == "DEGRADED_WITHOUT_RATIO"
    assert result.window is w


def test_trop_de_mesures_pour_la_fenetre_est_retenu():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(1, 40.0, 0.1, 0.0)] * 13)

    result = build(w, REF, "FREE_FLOW")

    assert isinstance(result, Withheld) and result.reason_code == "SAMPLE_OVERFLOW"


def test_un_troncon_inconnu_est_retenu():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(1, 40.0, 0.1, 0.0)])
    w.road_segment_id = "ROAD_404"

    result = build(w, REF, "FREE_FLOW")

    assert isinstance(result, Withheld) and result.reason_code == "UNKNOWN_SEGMENT"


def test_un_debit_hors_borne_est_retenu_par_le_controle_final():
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(5000, 40.0, 0.1, 0.0)] * 6)

    result = build(w, REF, "FREE_FLOW")

    assert isinstance(result, Withheld) and result.reason_code == "INDICATOR_INVALID"
    assert "flow_veh_per_min" in result.reason


# ------------------------------------------- arrondis de l'entrepôt, moitié vers le haut


def test_les_valeurs_sont_arrondies_a_la_precision_de_l_entrepot():
    """Flux 2 décimales, vitesse 1, occupation 3, file 1, ratio 3 : ce que l'entrepôt garde."""
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(3, 33.3333, 0.123456, 12.349)] * 6)

    data = built(w, "SLOW").event["data"]

    assert data["flow_veh_per_min"] == 18.0
    assert data["average_speed_kmh"] == 33.3
    assert data["occupancy_rate"] == 0.123
    assert data["max_queue_length_m"] == 12.3
    assert data["speed_ratio"] == 0.667  # calculé sur la vitesse non arrondie : 33,3333 ÷ 50


def test_une_egalite_exacte_est_arrondie_vers_le_haut_comme_postgresql():
    # moyenne exacte 0,3125 : round() de Python donne 0,312 (arrondi au pair), PostgreSQL 0,313
    rows = [(1, 40.0, o, 0.0) for o in (0.31, 0.31, 0.31, 0.32)]
    w = window("ROAD_001", "INT_01", "2026-10-20T08:00:00Z", rows)

    assert built(w, "FREE_FLOW").event["data"]["occupancy_rate"] == 0.313

    # moyenne exacte 38,45 (deux mesures d'un véhicule à 38,4 et 38,5) : 38,5, et non 38,4
    w = window(
        "ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(1, 38.4, 0.2, 0.0), (1, 38.5, 0.2, 0.0)]
    )
    assert built(w, "FREE_FLOW").event["data"]["average_speed_kmh"] == 38.5


def test_les_sommes_sont_exactes_pas_flottantes():
    # 0,1 + 0,2 vaut 0,30000000000000004 en flottant ; la moyenne exacte de 0,1 et 0,2 est 0,15
    w = window(
        "ROAD_001", "INT_01", "2026-10-20T08:00:00Z", [(1, 40.0, 0.1, 0.0), (1, 40.0, 0.2, 0.0)]
    )

    assert w.exact_occupancy == Decimal("0.15")
