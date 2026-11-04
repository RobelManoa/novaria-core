"""Validation d'une mesure reçue : accepter, ou rejeter avec un motif (MS-08)."""

import json
import secrets

import pytest

from app.services.validation import (
    MAX_REASON_CHARS,
    Rejection,
    Valid,
    instant_ms,
    semantic_errors,
    validate_measurement,
)
from tests.support import body, example, measurement, with_value, without

LIMIT = 65536


def check(payload: bytes | object, **kwargs) -> Valid | Rejection:
    raw = payload if isinstance(payload, bytes) else body(payload)
    return validate_measurement(raw, max_bytes=kwargs.get("max_bytes", LIMIT))


# --- Messages conformes -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["mesure-valide.json", "mesure-partielle.json", "mesure-route-vide.json"]
)
def test_the_examples_of_the_contract_are_accepted(name):
    result = check(example(name))
    assert isinstance(result, Valid), result
    assert result.event_id == example(name)["id"]


def test_a_valid_message_keeps_the_object_exactly_as_received():
    event = measurement(3)
    result = check(event)
    assert isinstance(result, Valid)
    assert result.event == event


def test_numbers_written_as_integers_are_accepted_where_the_schema_wants_numbers():
    result = check(measurement(0, occupancy_rate=1, average_speed_kmh=40, queue_length_m=0))
    assert isinstance(result, Valid), result


# --- Illisible --------------------------------------------------------------------------------


def test_bytes_that_are_not_utf8_are_unreadable_and_kept_as_text():
    result = check(b'{"id": "\xff\xfe"}')
    assert isinstance(result, Rejection)
    assert result.reason_code == "UNREADABLE"
    assert isinstance(result.original_payload, str)
    assert result.intersection_id is None


def test_truncated_json_is_unreadable_and_kept_as_the_text_received():
    text = json.dumps(measurement(0))[:60]
    result = check(text.encode())
    assert isinstance(result, Rejection)
    assert result.reason_code == "UNREADABLE"
    assert result.original_payload == text
    assert "position" in result.reason


@pytest.mark.parametrize("text", [b"NaN", b'{"a": Infinity}', b'{"a": -Infinity}'])
def test_the_json_constants_python_tolerates_are_refused(text):
    result = check(text)
    assert isinstance(result, Rejection)
    assert result.reason_code == "UNREADABLE"


def test_a_message_nested_too_deep_is_unreadable_not_a_crash():
    result = check(b"[" * 100_000, max_bytes=200_000)
    assert isinstance(result, Rejection)
    assert result.reason_code == "UNREADABLE"


def test_an_empty_body_is_unreadable():
    result = check(b"")
    assert isinstance(result, Rejection)
    assert result.reason_code == "UNREADABLE"


def test_a_message_over_the_limit_is_refused_without_being_parsed():
    result = check(b"x" * 101, max_bytes=100)
    assert isinstance(result, Rejection)
    assert result.reason_code == "UNREADABLE"
    assert "100" in result.reason
    assert result.original_payload == "x" * 101


# --- Pas un objet, ni le bon type -------------------------------------------------------------


@pytest.mark.parametrize("value", [[], [1, 2], 42, "texte", None, True])
def test_json_that_is_not_an_object_violates_the_contract(value):
    result = check(value)
    assert isinstance(result, Rejection)
    assert result.reason_code == "CONTRACT_VIOLATION"
    assert result.original_payload == value
    assert result.intersection_id is None


def test_another_event_type_is_refused_as_unknown_here():
    indicator = example("indicateur-fluide.json")
    result = check(indicator)
    assert isinstance(result, Rejection)
    assert result.reason_code == "UNKNOWN_TYPE"
    assert "novaria.traffic.indicator.v1" in result.reason
    assert result.intersection_id == indicator["subject"]


def test_an_unknown_type_is_truncated_in_the_reason():
    result = check(with_value(measurement(0), ("type",), "novaria." + "x" * 500 + ".v1"))
    assert isinstance(result, Rejection)
    assert result.reason_code == "UNKNOWN_TYPE"
    assert len(result.reason) < 300


def test_a_missing_type_is_a_contract_violation():
    result = check(without(measurement(0), "type"))
    assert isinstance(result, Rejection)
    assert result.reason_code == "CONTRACT_VIOLATION"


# --- Contrat ----------------------------------------------------------------------------------

CONTRACT_BREAKS = {
    "champ obligatoire absent": lambda e: without(e, "data", "quality"),
    "champ de l'enveloppe absent": lambda e: without(e, "domain"),
    "champ inconnu à la racine": lambda e: {**e, "extra": 1},
    "champ inconnu dans data": lambda e: with_value(e, ("data", "vitesse_max"), 90),
    "borne dépassée": lambda e: with_value(e, ("data", "occupancy_rate"), 1.7),
    "borne négative": lambda e: with_value(e, ("data", "vehicle_count"), -1),
    "mauvais type": lambda e: with_value(e, ("data", "vehicle_count"), "quatre"),
    "décimal pour un entier": lambda e: with_value(e, ("data", "vehicle_count"), 4.5),
    "booléen pour un entier": lambda e: with_value(e, ("data", "vehicle_count"), True),
    "date sans fuseau": lambda e: with_value(e, ("time",), "2026-10-20T08:00:10"),
    "date impossible": lambda e: with_value(e, ("time",), "2026-13-45T08:00:10Z"),
    "capteur mal formé": lambda e: with_value(e, ("data", "sensor_id"), "CAPTEUR_1"),
    "carrefour mal formé": lambda e: with_value(e, ("data", "intersection_id"), "INT_1"),
    "version de schéma": lambda e: with_value(e, ("schema_version",), "2.0"),
    "domaine": lambda e: with_value(e, ("domain",), "traffic"),
    "qualité inconnue": lambda e: with_value(e, ("data", "quality", "status"), "GOOD"),
    "drapeau inconnu": lambda e: with_value(e, ("data", "quality", "flags"), ["BROKEN"]),
    "drapeaux en double": lambda e: with_value(
        e, ("data", "quality", "flags"), ["IMPLAUSIBLE_VALUE", "IMPLAUSIBLE_VALUE"]
    ),
    "vitesse malgré zéro véhicule": lambda e: with_value(
        with_value(e, ("data", "vehicle_count"), 0), ("data", "average_speed_kmh"), 30.0
    ),
    "VALID sans occupation": lambda e: with_value(e, ("data", "occupancy_rate"), None),
    "VALID avec véhicules sans vitesse": lambda e: with_value(
        e, ("data", "average_speed_kmh"), None
    ),
    "SIMULATED sans graine": lambda e: without(e, "data", "provenance", "seed"),
    "provenance inconnue": lambda e: with_value(e, ("data", "provenance", "source_type"), "MAGIC"),
    "source mal formée": lambda e: with_value(e, ("source",), "Simulateur Majuscule"),
    "id vide": lambda e: with_value(e, ("id",), ""),
    "id trop long": lambda e: with_value(e, ("id",), "x" * 201),
    "queue_length_m nul": lambda e: with_value(e, ("data", "queue_length_m"), None),
}


@pytest.mark.parametrize("name", sorted(CONTRACT_BREAKS))
def test_every_kind_of_contract_break_is_refused_with_a_path_and_a_message(name):
    result = check(CONTRACT_BREAKS[name](measurement(0)))
    assert isinstance(result, Rejection), name
    assert result.reason_code == "CONTRACT_VIOLATION", result.reason
    assert result.reason, "un motif est toujours donné"
    assert result.errors, "chaque défaut est listé avec son champ"
    for item in result.errors:
        assert item["field"].startswith("body")
        assert item["message"]


def test_the_reason_names_the_faulty_field_like_the_examples_of_the_contract():
    result = check(with_value(measurement(0), ("data", "occupancy_rate"), 1.7))
    assert isinstance(result, Rejection)
    assert result.reason.startswith("data/occupancy_rate : ")
    assert result.errors[0]["field"] == "body.data.occupancy_rate"
    assert result.original_payload["data"]["occupancy_rate"] == 1.7


def test_the_carrefour_of_a_rejected_message_is_kept_when_it_can_be_read():
    result = check(with_value(measurement(0), ("data", "occupancy_rate"), 1.7))
    assert isinstance(result, Rejection)
    assert result.intersection_id == "INT_01"
    assert result.original_key == "INT_01"


def test_the_carrefour_is_taken_from_the_subject_when_data_has_none_and_dropped_when_malformed():
    broken = without(measurement(0), "data", "intersection_id")
    assert check(broken).intersection_id == "INT_01"
    assert check(with_value(broken, ("subject",), "pas-un-carrefour")).intersection_id is None


def test_a_rejection_never_repeats_the_value_that_was_refused():
    leaked = secrets.token_urlsafe(24)
    result = check(with_value(measurement(0), ("data", "vehicle_count"), leaked))
    assert isinstance(result, Rejection)
    assert leaked not in result.reason
    assert all(leaked not in item["message"] for item in result.errors)


def test_a_very_long_reason_is_cut_to_the_size_the_contract_allows():
    event = measurement(0)
    event["data"].update({f"extra_{i}": "x" * 100 for i in range(100)})
    result = check(event, max_bytes=200_000)
    assert isinstance(result, Rejection)
    assert len(result.reason) <= MAX_REASON_CHARS


# --- Règles entre champs ----------------------------------------------------------------------

SEMANTIC_BREAKS = {
    "sujet différent du carrefour": lambda e: with_value(e, ("subject",), "INT_02"),
    "id sans rapport avec l'instant": lambda e: with_value(
        e, ("id",), e["id"].rsplit(":", 1)[0] + ":1"
    ),
    "id d'un autre capteur": lambda e: with_value(
        e, ("id",), e["id"].replace("SENSOR_001", "SENSOR_002")
    ),
    "id d'une autre exécution": lambda e: with_value(
        e, ("id",), e["id"].replace("run-test", "run-autre")
    ),
    "PARTIAL sans drapeau": lambda e: with_value(
        with_value(e, ("data", "quality", "status"), "PARTIAL"),
        ("data", "quality", "flags"),
        ["GAP_BEFORE"],
    ),
    "PARTIAL sans liste de drapeaux": lambda e: with_value(
        e, ("data", "quality", "status"), "PARTIAL"
    ),
    "SUSPECT sans IMPLAUSIBLE_VALUE": lambda e: with_value(
        with_value(e, ("data", "quality", "status"), "SUSPECT"),
        ("data", "quality", "flags"),
        ["LATE"],
    ),
}


@pytest.mark.parametrize("name", sorted(SEMANTIC_BREAKS))
def test_a_rule_between_fields_that_the_schema_cannot_express_is_enforced(name):
    result = check(SEMANTIC_BREAKS[name](measurement(0)))
    assert isinstance(result, Rejection), name
    assert result.reason_code == "SEMANTIC_VIOLATION", result.reason
    assert result.errors


def test_a_suspect_measurement_with_its_flag_and_a_partial_one_with_its_flag_are_accepted():
    suspect = with_value(
        measurement(0), ("data", "quality"), {"status": "SUSPECT", "flags": ["IMPLAUSIBLE_VALUE"]}
    )
    partial = example("mesure-partielle.json")
    assert isinstance(check(suspect), Valid)
    assert isinstance(check(partial), Valid)


def test_the_id_is_checked_against_the_millisecond_of_the_time_with_fractions():
    event = measurement(0)
    event["time"] = "2026-10-20T08:00:10.250Z"
    event["id"] = f"run-test:SENSOR_001:{instant_ms(event['time'])}"
    assert isinstance(check(event), Valid)
    assert event["id"].endswith(":1792483210250")


def test_semantic_errors_lists_every_broken_rule_at_once():
    from app.schemas.events import MeasurementEvent

    event = with_value(
        with_value(measurement(0), ("subject",), "INT_02"), ("id",), "run-test:SENSOR_001:1"
    )
    errors = semantic_errors(MeasurementEvent.model_validate(event))
    assert len(errors) == 2
