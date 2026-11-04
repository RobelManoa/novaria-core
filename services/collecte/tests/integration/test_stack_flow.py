"""Le critère de MS-08 contre un vrai Kafka et un vrai MongoDB.

Tous les messages valides arrivent sur `iot.raw`, tous les invalides sur le sujet d'erreurs
`errors.dlq`, les doublons sont ignorés.
"""

import json
import subprocess
import sys
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest
from pymongo.errors import DuplicateKeyError, OperationFailure, WriteError

from app.api import deps
from app.cli import main as cli_main
from app.core.config import get_settings
from app.services.ingestion import Outcome
from tests.integration import stack
from tests.integration.conftest import new_service
from tests.support import (
    assert_published_conforms,
    body,
    example,
    measurement,
    with_value,
)

pytestmark = stack.needs_stack

SIMULATOR = Path(__file__).resolve().parents[4] / "simulator" / "app.py"


def on_topic(topic: str, run_id: str, field=lambda event: event["id"]):
    """Les messages du sujet qui appartiennent à cet essai."""
    return stack.read_topic(topic, lambda r: str(field(r.event)).startswith(run_id))


def post(client, payload, run_id: str):
    raw = payload if isinstance(payload, bytes) else body(payload)
    return client.post("/api/v1/measurements", content=raw, headers={"X-Correlation-ID": run_id})


def messages_of_the_run(run_id: str):
    valid = [measurement(n, sensor, run_id=run_id) for n in range(10) for sensor in (1, 2, 3)]
    broken = {
        "CONTRACT_VIOLATION": with_value(
            measurement(40, run_id=run_id), ("data", "occupancy_rate"), 1.7
        ),
        "SEMANTIC_VIOLATION": with_value(measurement(41, run_id=run_id), ("subject",), "INT_02"),
        "UNKNOWN_TYPE": {**example("indicateur-fluide.json"), "id": f"{run_id}:indicateur"},
        "UNREADABLE": f'{{"id": "{run_id}:tronque", "source": "simulateur/'.encode(),
        "NOT_AN_OBJECT": [1, 2, 3, run_id],
        "TOO_BIG": (f'{{"id": "{run_id}:gros", "padding": "' + "x" * 70_000 + '"}').encode(),
    }
    return valid, broken


def test_valid_messages_reach_iot_raw_invalid_ones_the_error_topic_and_duplicates_are_ignored(
    http, run_id
):
    valid, broken = messages_of_the_run(run_id)
    statuses = []
    for event in valid:
        statuses.append(post(http, event, run_id))
    for event in broken.values():
        statuses.append(post(http, event, run_id))
    resent = valid[:10]
    for _ in range(2):
        for event in resent:
            statuses.append(post(http, event, run_id))

    answers = Counter(
        (r.status_code, r.json().get("status")) for r in statuses if r.status_code == 202
    )
    assert answers == {(202, "ACCEPTED"): 30, (202, "DUPLICATE"): 20}
    assert Counter(r.status_code for r in statuses if r.status_code != 202) == {422: 6}

    # --- iot.raw : les 30 mesures valides, une seule fois chacune, rien d'autre
    on_raw = on_topic("iot.raw", run_id)
    ids = [r.event["id"] for r in on_raw]
    assert sorted(ids) == sorted(e["id"] for e in valid), "tous les valides, aucun autre"
    assert max(Counter(ids).values()) == 1, "aucun doublon sur iot.raw"
    for record in on_raw:
        assert_published_conforms("iot.raw", record.event)
        assert record.key == record.event["subject"].encode()

    # --- errors.dlq : les 6 invalides, avec leur motif, conformes au contrat
    on_dlq = stack.read_topic("errors.dlq", lambda r: r.event.get("correlation_id") == run_id)
    reasons = Counter(r.event["data"]["reason_code"] for r in on_dlq)
    assert reasons == {
        "CONTRACT_VIOLATION": 2,  # une borne dépassée, et un JSON qui n'est pas un objet
        "SEMANTIC_VIOLATION": 1,
        "UNKNOWN_TYPE": 1,
        "UNREADABLE": 2,  # JSON tronqué, et message de plus de 64 Kio
    }, reasons
    for record in on_dlq:
        assert_published_conforms("errors.dlq", record.event)
        assert record.event["data"]["reason"]
        assert record.event["source"] == "collecte"
    by_code = {r.event["data"]["reason_code"]: r.event for r in on_dlq}
    assert by_code["UNKNOWN_TYPE"]["data"]["original_payload"]["id"] == f"{run_id}:indicateur"
    truncated = [r.event for r in on_dlq if r.event["data"]["reason_code"] == "UNREADABLE"]
    assert all(isinstance(e["data"]["original_payload"], str) for e in truncated)
    assert not [r for r in on_raw if r.event["id"].endswith(("indicateur", "tronque", "gros"))]

    # --- MongoDB : la copie brute des valides, l'archive des rejets
    stored = stack.raw_events_of(run_id)
    assert sorted(d["id"] for d in stored) == sorted(e["id"] for e in valid)
    assert all(
        isinstance(d["time"], datetime) and isinstance(d["received_at"], datetime) for d in stored
    )
    archived = stack.rejects_of(run_id)
    assert len(archived) == 6
    assert {d["service"] for d in archived} == {"collecte"}
    assert {d["source_topic"] for d in archived} == {"iot.raw"}
    assert all(d["reason"] for d in archived)


def test_duplicates_are_recognised_by_a_brand_new_instance_nothing_is_kept_in_memory(
    real_service, run_id
):
    events = [measurement(n, run_id=run_id) for n in range(5)]
    assert [real_service.receive(body(e)).outcome for e in events] == [Outcome.ACCEPTED] * 5
    other, closers = new_service()  # un autre processus : mémoire vide, mêmes bases
    try:
        assert [other.receive(body(e)).outcome for e in events] == [Outcome.DUPLICATE] * 5
    finally:
        for close in closers:
            close()
    assert len(on_topic("iot.raw", run_id)) == 5
    assert len(stack.raw_events_of(run_id)) == 5


def test_fifty_simultaneous_copies_of_one_message_give_one_message_on_iot_raw(real_service, run_id):
    raw = body(measurement(0, run_id=run_id))
    outcomes: list[Outcome] = []
    gate = threading.Barrier(50)

    def send() -> None:
        gate.wait()
        outcomes.append(real_service.receive(raw).outcome)

    threads = [threading.Thread(target=send) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert Counter(outcomes) == {Outcome.ACCEPTED: 1, Outcome.DUPLICATE: 49}
    assert len(on_topic("iot.raw", run_id)) == 1
    assert len(stack.raw_events_of(run_id)) == 1


def test_two_instances_racing_on_the_same_message_store_it_once_the_index_decides(run_id):
    """Limite connue : deux instances peuvent publier deux fois ; MongoDB n'accepte qu'une copie."""
    first, closers_a = new_service()
    second, closers_b = new_service()
    raw = body(measurement(0, run_id=run_id))
    outcomes: list[Outcome] = []
    gate = threading.Barrier(40)

    def send(service) -> None:
        gate.wait()
        outcomes.append(service.receive(raw).outcome)

    threads = [threading.Thread(target=send, args=(s,)) for s in [first, second] * 20]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        for close in [*closers_a, *closers_b]:
            close()
    assert set(outcomes) <= {Outcome.ACCEPTED, Outcome.DUPLICATE}
    assert outcomes.count(Outcome.ACCEPTED) >= 1
    assert len(stack.raw_events_of(run_id)) == 1, "l'index unique garantit une seule copie"
    published = len(on_topic("iot.raw", run_id))
    assert 1 <= published <= 2, f"au plus une publication par instance, mesuré : {published}"


def test_the_messages_of_one_crossroad_stay_in_order_on_one_partition(http, run_id):
    events = [measurement(n, sensor, run_id=run_id) for n in range(6) for sensor in (1, 2, 3)]
    for event in events:
        assert post(http, event, run_id).status_code == 202
    on_raw = on_topic("iot.raw", run_id)
    assert len({r.partition for r in on_raw}) == 1, "même clé (carrefour), même partition"
    in_log_order = [r.event["id"] for r in sorted(on_raw, key=lambda r: r.offset)]
    assert in_log_order == [e["id"] for e in events], "l'ordre d'envoi est l'ordre du sujet"


def test_a_payload_that_bson_refuses_is_archived_as_text_and_still_reaches_the_error_topic(
    real_service, run_id
):
    nasty = ('{"id": "' + run_id + ':nul", "a\\u0000b": 1}').encode()
    receipt = real_service.receive(nasty, correlation_id=run_id)
    assert receipt.outcome is Outcome.REJECTED
    (dlq,) = stack.read_topic("errors.dlq", lambda r: r.event.get("correlation_id") == run_id)
    assert dlq.event["data"]["original_payload"] == {"id": f"{run_id}:nul", "a\x00b": 1}
    (archived,) = stack.rejects_of(run_id)
    assert isinstance(archived["original_payload"], str)
    assert json.loads(archived["original_payload"]) == dlq.event["data"]["original_payload"]


# --- Ce que MongoDB garantit à la collecte (les hypothèses de sa conception) -----------------


def test_the_service_account_can_insert_and_find_but_not_update_or_delete(run_id):
    with stack.mongo() as client:
        collection = client[stack.database_name()]["raw_events"]
        document = {
            **measurement(0, run_id=run_id),
            "time": datetime(2026, 10, 20, 8, 0, 10),
            "received_at": datetime(2026, 11, 5),
        }
        collection.insert_one(dict(document))
        assert collection.find_one({"id": document["id"]}) is not None
        with pytest.raises(OperationFailure):
            collection.update_one({"id": document["id"]}, {"$set": {"source": "autre"}})
        with pytest.raises(OperationFailure):
            collection.delete_one({"id": document["id"]})


def test_the_unique_index_refuses_a_second_copy_and_the_validator_a_message_without_provenance(
    run_id,
):
    with stack.mongo() as client:
        collection = client[stack.database_name()]["raw_events"]
        document = {
            **measurement(0, run_id=run_id),
            "time": datetime(2026, 10, 20, 8, 0, 10),
            "received_at": datetime(2026, 11, 5),
        }
        collection.insert_one(dict(document))
        with pytest.raises(DuplicateKeyError):
            collection.insert_one(dict(document))
        without_provenance = {**document, "id": f"{run_id}:sans", "data": {}}
        with pytest.raises(WriteError):
            collection.insert_one(without_provenance)


# --- « MQTT simulé » : le fichier du simulateur rejoué, avec redélivrance ---------------------


def test_the_simulator_file_replayed_through_simulated_mqtt_with_redelivery_lands_once(
    tmp_path, monkeypatch, run_id, capsys
):
    out = tmp_path / "run"
    subprocess.run(  # noqa: S603 - notre interpréteur et le simulateur du dépôt
        [
            sys.executable, str(SIMULATOR), "run", "--scenario", "heure-de-pointe", "--seed", "42",
            "--run-id", run_id, "--start", "2026-10-20T08:00:00Z", "--duration", "2m",
            "--anomaly", "doublon:sensor=SENSOR_001,at=+20,copies=1", "--out", str(out),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )  # fmt: skip
    lines = (out / "mesures.jsonl").read_bytes().split(b"\n")
    messages = [json.loads(line) for line in lines if line.strip()]
    distinct = {m["id"] for m in messages}
    assert len(distinct) == len(messages) - 1, "le doublon du simulateur"

    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", stack.BOOTSTRAP)
    monkeypatch.setenv("MONGO_URL", stack.MONGO_URL)
    monkeypatch.setenv("MONGO_DB", stack.database_name())
    get_settings.cache_clear()
    deps.close_components()
    try:
        code = cli_main(["replay-mqtt", str(out / "mesures.jsonl"), "--redeliver"])
    finally:
        deps.close_components()
    summary = capsys.readouterr().out
    assert code == 0
    assert f"ACCEPTED={len(distinct)}" in summary
    assert f"DUPLICATE={2 * len(messages) - len(distinct)}" in summary
    assert "REJECTED=0" in summary
    on_raw = on_topic("iot.raw", run_id)
    assert Counter(r.event["id"] for r in on_raw) == dict.fromkeys(distinct, 1)
    assert len(stack.raw_events_of(run_id)) == len(distinct)
