"""La collecte juge comme le contrat (MS-08) : mêmes décisions que `contracts/validate_events.py`.

Trois corpus, un même critère : un message est accepté par la collecte **si et seulement si**
`validate_events.py` (schéma JSON puis règles entre champs) le déclare valide.
- les exemples du contrat ;
- des messages dégradés (une infraction à la fois, schéma et règles entre champs) ;
- la sortie réelle du simulateur MS-07, avec ses quatre anomalies : valeur aberrante, capteur muet,
  doublon, retard. Tous ces messages sont conformes ; les doublons ont le même `id`.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from validate_events import validate_event

from app.services.ingestion import Outcome
from app.services.validation import Rejection, Valid, validate_measurement
from tests.contract.conftest import CONTRACTS
from tests.openapi_checks import COLLECTE
from tests.support import Rig, body, example, measurement
from tests.unit.test_validation import CONTRACT_BREAKS, SEMANTIC_BREAKS

SIMULATOR = CONTRACTS.parent / "simulator" / "app.py"


def ours(event: dict) -> bool:
    return isinstance(validate_measurement(body(event), max_bytes=65536), Valid)


def theirs(event: dict) -> bool:
    return validate_event(event) == []


# --- Mêmes décisions que le contrat -----------------------------------------------------------


@pytest.mark.parametrize(
    "path", sorted((CONTRACTS / "events" / "examples").glob("*.json")), ids=lambda p: p.name
)
def test_every_example_of_the_contract_gets_the_same_decision_as_the_contract(path):
    event = json.loads(path.read_text(encoding="utf-8"))
    if event["type"] == "novaria.iot.measurement.v1":
        assert ours(event) is theirs(event) is True
    else:
        assert not ours(event), "un autre type d'événement n'entre pas sur iot.raw"


# Cas où la collecte est PLUS stricte que la référence, et pourquoi. `validate_events.py` ne
# contrôle le format `date-time` que si un paquet optionnel (`rfc3339-validator`) est installé ;
# sans lui, une date impossible passe. La collecte la refuse : `time` devient une date BSON.
STRICTER_THAN_THE_REFERENCE = {"date impossible"}


@pytest.mark.parametrize("name", sorted(CONTRACT_BREAKS) + sorted(SEMANTIC_BREAKS))
def test_every_degraded_message_gets_the_same_decision_as_the_contract(name):
    makers = {**CONTRACT_BREAKS, **SEMANTIC_BREAKS}
    event = makers[name](measurement(0))
    assert ours(event) is False
    if name not in STRICTER_THAN_THE_REFERENCE:
        assert theirs(event) is False, f"le contrat accepte « {name} » : le cas est mal construit"


def test_the_only_leniency_of_the_reference_is_the_optional_date_check():
    lenient = [
        name
        for name, make in {**CONTRACT_BREAKS, **SEMANTIC_BREAKS}.items()
        if theirs(make(measurement(0)))
    ]
    assert set(lenient) <= STRICTER_THAN_THE_REFERENCE


def test_the_degraded_cases_cover_both_the_schema_and_the_rules_between_fields():
    reasons = {
        validate_measurement(body(m(measurement(0))), max_bytes=65536).reason_code
        for m in {**CONTRACT_BREAKS, **SEMANTIC_BREAKS}.values()
    }
    assert reasons == {"CONTRACT_VIOLATION", "SEMANTIC_VIOLATION"}


# --- La sortie réelle du simulateur -----------------------------------------------------------


def run_simulator(*extra: str) -> list[bytes]:
    done = subprocess.run(  # noqa: S603 - notre interpréteur et le simulateur du dépôt
        [
            sys.executable,
            str(SIMULATOR),
            "run",
            "--scenario",
            "heure-de-pointe",
            "--seed",
            "42",
            "--run-id",
            "run-parite",
            "--start",
            "2026-10-20T08:00:00Z",
            "--duration",
            "3m",
            "--stdout",
            *extra,
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    return [line for line in done.stdout.split(b"\n") if line.strip()]


ANOMALIES = (
    "--anomaly", "aberrante:sensor=SENSOR_003,at=+30,variant=vitesse",
    "--anomaly", "muet:sensor=SENSOR_007,at=+60,duration=1m",
    "--anomaly", "doublon:sensor=SENSOR_001,at=+20,copies=2",
    "--anomaly", "retard:sensor=SENSOR_010,at=+40,delay=45",
)  # fmt: skip


@pytest.fixture(scope="module")
def simulator_lines() -> list[bytes]:
    return run_simulator(*ANOMALIES)


def test_the_simulator_emits_messages_for_every_anomaly(simulator_lines):
    events = [json.loads(line) for line in simulator_lines]
    ids = [e["id"] for e in events]
    assert len(events) > 400
    assert len(ids) - len(set(ids)) == 2, "le doublon est livré 2 fois de plus : même id"
    assert any(e["data"]["quality"]["status"] == "SUSPECT" for e in events), "valeur aberrante"
    assert any("GAP_BEFORE" in e["data"]["quality"].get("flags", []) for e in events), (
        "capteur muet"
    )


def test_every_message_of_the_simulator_gets_the_same_decision_as_the_contract(simulator_lines):
    for line in simulator_lines:
        event = json.loads(line)
        assert theirs(event) is True
        assert ours(event) is True, event["id"]


def test_the_collecte_ends_with_exactly_the_distinct_ids_of_the_simulator(simulator_lines):
    rig = Rig()
    outcomes = [rig.service.receive(line).outcome for line in simulator_lines]
    distinct = {json.loads(line)["id"] for line in simulator_lines}
    assert outcomes.count(Outcome.ACCEPTED) == len(distinct)
    assert outcomes.count(Outcome.DUPLICATE) == len(simulator_lines) - len(distinct) == 2
    assert Outcome.REJECTED not in outcomes
    assert {e["id"] for e in rig.publisher.events("iot.raw")} == distinct
    assert len(rig.publisher.events("iot.raw")) == len(distinct), "aucun doublon n'est publié"
    assert set(rig.raw.documents) == distinct
    rig.publisher.assert_all_conform()


def test_a_late_message_is_accepted_by_the_collecte_the_lateness_is_judged_downstream(
    simulator_lines,
):
    """Le retard (DQ-04) se juge sur le temps d'événement du flux, pas à la réception."""
    late = [json.loads(line) for line in simulator_lines if b"SENSOR_010" in line]
    assert late
    assert all(ours(event) for event in late)


# --- Contrat OpenAPI de la collecte -----------------------------------------------------------


def test_the_route_is_in_the_contract_with_the_documented_answers():
    operation = COLLECTE["paths"]["/api/v1/measurements"]["post"]
    assert set(operation["responses"]) == {"202", "422", "5XX"}
    assert operation["x-internal"] is True


def test_the_service_declares_the_same_answers_as_the_contract():
    from app.main import app

    declared = app.openapi()["paths"]["/api/v1/measurements"]["post"]["responses"]
    assert "202" in declared
    assert "422" in declared
    assert "5XX" in declared


def test_the_request_body_of_the_contract_is_the_event_schema_of_the_bus():
    schema = COLLECTE["paths"]["/api/v1/measurements"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert schema == {"$ref": "../events/iot-measurement.schema.json"}
    assert Path(CONTRACTS / "events" / "iot-measurement.schema.json").is_file()


def test_the_examples_of_the_contract_answer_accepted_then_duplicate():
    rig = Rig()
    event = example("mesure-valide.json")
    first = rig.service.receive(body(event))
    again = rig.service.receive(body(event))
    assert (first.outcome, again.outcome) == (Outcome.ACCEPTED, Outcome.DUPLICATE)
    assert isinstance(validate_measurement(body(event), max_bytes=65536), Valid)
    assert not isinstance(validate_measurement(body(event), max_bytes=65536), Rejection)
