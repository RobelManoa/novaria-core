"""Kafka et MongoDB réels pour les tests d'intégration de la collecte (MS-08).

Ignorés sans `NOVARIA_TEST_KAFKA_BOOTSTRAP` et `NOVARIA_TEST_MONGO_URL` :
`python scripts/dev/dev.py test-integration --service collecte` les fournit (projet Compose jetable,
sujets créés par `infra/kafka/init-topics.sh`, comptes de service de `db/mongo/init/`).
"""

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from kafka import KafkaConsumer, TopicPartition
from kafka.errors import KafkaError
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri

BOOTSTRAP = os.environ.get("NOVARIA_TEST_KAFKA_BOOTSTRAP")
MONGO_URL = os.environ.get("NOVARIA_TEST_MONGO_URL")  # compte svc_collecte : find et insert
MONGO_ADMIN_URL = os.environ.get("NOVARIA_TEST_MONGO_ADMIN_URL")  # efface les traces d'essai

needs_stack = pytest.mark.skipif(
    not (BOOTSTRAP and MONGO_URL),
    reason="Kafka et MongoDB requis (NOVARIA_TEST_KAFKA_BOOTSTRAP, NOVARIA_TEST_MONGO_URL)",
)


def database_name() -> str:
    return parse_uri(MONGO_URL)["database"]


@dataclass(frozen=True)
class Record:
    partition: int
    offset: int
    key: bytes | None
    value: bytes

    @property
    def event(self) -> dict:
        return json.loads(self.value)


def _create_consumer(box: dict) -> None:
    try:
        box["consumer"] = KafkaConsumer(
            bootstrap_servers=BOOTSTRAP,
            group_id=None,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            request_timeout_ms=15000,
            client_id="novaria-collecte-tests",
        )
    except KafkaError as error:
        box["error"] = error


def new_consumer(attempts: int = 4, wait_s: float = 10) -> KafkaConsumer:
    """Un consommateur. `kafka-python` peut rester suspendu à l'amorçage (`kafka_publisher.py`) :
    chaque essai a une limite ferme, puis un client neuf prend le relais."""
    for _ in range(attempts):
        box: dict = {}
        thread = threading.Thread(target=_create_consumer, args=(box,), daemon=True)
        thread.start()
        thread.join(wait_s)
        if "consumer" in box:
            return box["consumer"]
    raise AssertionError(f"consommateur Kafka : amorçage impossible en {attempts} essais")


def read_topic(topic: str, keep: Callable[[Record], bool] = lambda _: True) -> list[Record]:
    """Tout le contenu du sujet, du début à la fin actuelle, filtré par `keep`."""
    consumer = new_consumer()
    try:
        partitions = [
            TopicPartition(topic, p) for p in sorted(consumer.partitions_for_topic(topic) or [])
        ]
        consumer.assign(partitions)
        consumer.seek_to_beginning(*partitions)
        ends = consumer.end_offsets(partitions)
        found: list[Record] = []
        deadline = time.monotonic() + 30
        while (
            any(consumer.position(p) < ends[p] for p in partitions) and time.monotonic() < deadline
        ):
            for batch in consumer.poll(timeout_ms=500).values():
                for message in batch:
                    record = Record(message.partition, message.offset, message.key, message.value)
                    if keep(record):
                        found.append(record)
        return found
    finally:
        consumer.close()


def mongo(url: str | None = None) -> MongoClient:
    return MongoClient(url or MONGO_URL, serverSelectionTimeoutMS=5000)


def raw_events_of(run_id: str) -> list[dict]:
    with mongo() as client:
        return list(client[database_name()]["raw_events"].find({"id": {"$regex": f"^{run_id}:"}}))


def rejects_of(correlation_id: str) -> list[dict]:
    with mongo() as client:
        return list(client[database_name()]["rejects"].find({"correlation_id": correlation_id}))


def erase(run_id: str) -> None:
    """Efface les traces d'un essai : le compte de service ne peut pas supprimer, l'admin oui."""
    if not MONGO_ADMIN_URL:
        return
    with mongo(MONGO_ADMIN_URL) as client:
        database = client[database_name()]
        database["raw_events"].delete_many({"id": {"$regex": f"^{run_id}:"}})
        database["rejects"].delete_many({"correlation_id": run_id})
