"""Nettoyage d'un message `iot.raw` : acceptation, ou rejet avec son motif (DQ-01 à DQ-10)."""

import pytest

from app.flux.cleaning import clean
from app.flux.model import Measurement, Rejection

from .support import epoch_ms, example, message, raw, referential

REF = referential()


def rejected(payload: bytes, **kwargs) -> Rejection:
    result = clean(payload, REF, **kwargs)
    assert isinstance(result, Rejection), result
    return result


def test_accepte_l_exemple_du_contrat():
    result = clean(raw(example("mesure-valide.json")), REF, key=b"INT_01", partition=2, offset=17)

    assert isinstance(result, Measurement)
    assert result.id == "run-demo-0001:SENSOR_001:1792483210000"
    assert (result.sensor_id, result.road_segment_id, result.intersection_id) == (
        "SENSOR_001",
        "ROAD_001",
        "INT_01",
    )
    assert (
        result.vehicle_count,
        result.speed_kmh,
        result.occupancy_rate,
        result.queue_length_m,
    ) == (4, 38.5, 0.31, 22.0)
    assert (result.status, result.flags) == ("VALID", ())
    assert (result.partition, result.offset) == (2, 17)
    assert result.provenance == {
        "source_type": "SIMULATED",
        "run_id": "run-demo-0001",
        "scenario_id": "heure-de-pointe",
        "seed": 42,
    }


def test_l_instant_est_la_fin_de_l_intervalle_et_le_debut_en_decoule():
    result = clean(raw(message(time="2026-10-20T08:00:10Z")), REF)

    assert result.time_ms == epoch_ms("2026-10-20T08:00:10Z")
    assert result.start_ms == epoch_ms("2026-10-20T08:00:00Z")


def test_conserve_une_mesure_partielle_avec_ses_drapeaux():
    result = clean(
        raw(message(count=3, speed=None, status="PARTIAL", flags=["MISSING_SPEED"])), REF
    )

    assert isinstance(result, Measurement)
    assert (result.status, result.flags, result.speed_kmh) == ("PARTIAL", ("MISSING_SPEED",), None)


def test_conserve_une_mesure_suspecte_pour_que_les_fenetres_l_excluent():
    result = clean(
        raw(message(count=500, speed=190.0, status="SUSPECT", flags=["IMPLAUSIBLE_VALUE"])), REF
    )

    assert isinstance(result, Measurement)
    assert result.status == "SUSPECT"


@pytest.mark.parametrize(
    "payload", [b"\xff\xfe\x00", b"{pas du json", b"", b'{"a": NaN}', b'{"a": Infinity}']
)
def test_refuse_un_message_illisible(payload):
    result = rejected(payload)

    assert result.reason_code == "UNREADABLE"
    assert result.intersection_id is None
    assert isinstance(result.original_payload, str)


@pytest.mark.parametrize("payload", [b"[1, 2]", b'"texte"', b"42", b"null"])
def test_refuse_un_json_qui_n_est_pas_un_objet(payload):
    assert rejected(payload).reason_code == "CONTRACT_VIOLATION"


def test_refuse_un_type_d_evenement_inattendu_sur_iot_raw():
    document = message()
    document["type"] = "novaria.traffic.indicator.v1"

    result = rejected(raw(document))

    assert result.reason_code == "UNKNOWN_TYPE"
    assert "novaria.traffic.indicator.v1" in result.reason
    assert result.intersection_id == "INT_01"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["data"].update(vehicle_count=-1),
        lambda d: d["data"].update(average_speed_kmh=250.0),
        lambda d: d["data"].update(occupancy_rate=1.5),
        lambda d: d["data"].pop("interval_s"),
        lambda d: d["data"].update(vehicle_count=0, average_speed_kmh=30.0),
        lambda d: d.update(extra="champ inconnu"),
        lambda d: d.update(time="2026-02-30T08:00:00Z"),
    ],
)
def test_refuse_un_message_contraire_au_contrat(mutate):
    document = message()
    mutate(document)

    result = rejected(raw(document))

    assert result.reason_code == "CONTRACT_VIOLATION"
    assert result.reason


def test_le_motif_ne_reprend_jamais_la_valeur_refusee():
    document = message()
    document["data"]["average_speed_kmh"] = 98765.4321

    result = rejected(raw(document))

    assert "98765" not in result.reason


def test_resume_les_defauts_au_dela_de_cinq():
    document = message()
    document["data"].update(
        vehicle_count=-1,
        average_speed_kmh=999.0,
        occupancy_rate=9.0,
        interval_s=0,
        queue_length_m=-3.0,
    )
    document["data"]["sensor_id"] = "S1"
    document["data"]["road_segment_id"] = "R1"

    reason = rejected(raw(document)).reason

    assert "autre" in reason and reason.count(";") == 4


def test_identifie_le_carrefour_et_la_fenetre_d_un_message_refuse():
    document = message(time="2026-10-20T08:03:40Z")  # intervalle 08:03:30 à 08:03:40
    document["data"]["vehicle_count"] = -1

    result = rejected(raw(document), key=b"INT_01", partition=1, offset=5)

    assert result.intersection_id == "INT_01"
    assert result.window_start_ms == epoch_ms("2026-10-20T08:03:00Z")
    assert (result.original_key, result.partition, result.offset) == ("INT_01", 1, 5)


def test_un_carrefour_mal_forme_n_est_pas_repris():
    document = message()
    document["data"]["intersection_id"] = "carrefour; DROP TABLE"
    document["subject"] = "carrefour; DROP TABLE"

    assert rejected(raw(document)).intersection_id is None


def test_refuse_un_sujet_different_du_carrefour():
    document = message()
    document["subject"] = "INT_02"

    result = rejected(raw(document))

    assert result.reason_code == "SEMANTIC_VIOLATION"
    assert "subject" in result.reason


def test_refuse_un_identifiant_qui_ne_suit_pas_la_regle():
    document = message()
    document["id"] = "n-importe-quoi"

    result = rejected(raw(document))

    assert result.reason_code == "SEMANTIC_VIOLATION"
    assert "id attendu" in result.reason


def test_refuse_partial_sans_drapeau_et_suspect_sans_drapeau():
    partial = message(count=3, speed=None, status="PARTIAL")
    suspect = message(count=500, speed=190.0, status="SUSPECT")

    assert rejected(raw(partial)).reason_code == "SEMANTIC_VIOLATION"
    assert rejected(raw(suspect)).reason_code == "SEMANTIC_VIOLATION"


def test_refuse_un_capteur_inconnu():
    result = rejected(raw(message(sensor="SENSOR_999")))

    assert result.reason_code == "UNKNOWN_SENSOR"
    assert result.road_segment_id == "ROAD_001"


def test_refuse_un_capteur_declare_sur_un_autre_troncon():
    result = rejected(raw(message(sensor="SENSOR_003", road="ROAD_001")))

    assert result.reason_code == "UNKNOWN_SENSOR"
    assert "différent" in result.reason


def test_refuse_un_troncon_absent_du_referentiel():
    ref = referential()
    del ref.segments["ROAD_002"]

    result = clean(raw(message(sensor="SENSOR_003", road="ROAD_002")), ref)

    assert isinstance(result, Rejection) and result.reason_code == "UNKNOWN_SENSOR"


def test_refuse_un_horodatage_dans_le_futur_au_dela_de_la_tolerance():
    document = message(time="2026-10-20T08:00:10Z")
    now = epoch_ms("2026-10-20T08:00:10Z")

    assert isinstance(
        clean(raw(document), REF, now_ms=now - 5_000), Measurement
    )  # exactement 5 s : toléré
    result = rejected(raw(document), now_ms=now - 5_001)
    assert result.reason_code == "FUTURE_TIMESTAMP"


def test_sans_horloge_le_futur_n_est_pas_juge():
    assert isinstance(
        clean(raw(message(time="2099-01-01T00:00:00Z")), REF, now_ms=None), Measurement
    )
