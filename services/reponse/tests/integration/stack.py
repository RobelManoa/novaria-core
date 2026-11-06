"""Kafka et MongoDB réels pour les tests d'intégration de la réponse (MS-12).

Ignorés sans `NOVARIA_TEST_KAFKA_BOOTSTRAP` et `NOVARIA_TEST_REPONSE_MONGO_URL` :
`python scripts/dev/dev.py test-integration --service reponse` les fournit (projet Compose jetable,
sujets créés par `infra/kafka/init-topics.sh`, comptes de service de `db/mongo/init/` : le compte du
service est `svc_reponse`, aux droits de production).
"""

import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri

# Clé de signature des jetons d'essai : générée à l'exécution, aucune valeur secrète dans le dépôt.
JWT_SECRET = secrets.token_urlsafe(48)
BOOTSTRAP = os.environ.get("NOVARIA_TEST_KAFKA_BOOTSTRAP")
MONGO_URL = os.environ.get("NOVARIA_TEST_REPONSE_MONGO_URL")  # compte svc_reponse : find, insert
MONGO_ADMIN_URL = os.environ.get("NOVARIA_TEST_REPONSE_MONGO_ADMIN_URL")  # relit et nettoie

needs_stack = pytest.mark.skipif(
    not (BOOTSTRAP and MONGO_URL and MONGO_ADMIN_URL),
    reason="Kafka et MongoDB requis (NOVARIA_TEST_KAFKA_BOOTSTRAP et NOVARIA_TEST_REPONSE_*)",
)


@dataclass(frozen=True)
class Record:
    partition: int
    offset: int
    key: bytes | None
    value: bytes

    @property
    def event(self) -> dict:
        return json.loads(self.value)


def wait_until(
    condition: Callable[[], object],
    seconds: float = 30,
    step: float = 0.05,
    why: Callable[[], str] | None = None,
):
    """Rend la valeur (vraie) de `condition` dès qu'elle l'est ; `AssertionError` sinon."""
    deadline = time.monotonic() + seconds
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() > deadline:
            detail = f" : {why()}" if why else ""
            raise AssertionError(f"condition non atteinte en {seconds} s{detail}")
        time.sleep(step)


# --------------------------------------------------------------------------------------- Kafka
def read_topic(topic: str, keep: Callable[[Record], bool] = lambda _: True) -> list[Record]:
    """Tout le contenu du sujet, du début à la fin actuelle, filtré par `keep`."""
    consumer = KafkaConsumer(
        bootstrap_servers=BOOTSTRAP,
        group_id=None,
        enable_auto_commit=False,
        request_timeout_ms=15000,
        client_id="novaria-reponse-tests",
    )
    try:
        parts = [
            TopicPartition(topic, n) for n in sorted(consumer.partitions_for_topic(topic) or ())
        ]
        consumer.assign(parts)
        consumer.seek_to_beginning(*parts)
        ends = consumer.end_offsets(parts)
        found: list[Record] = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and any(consumer.position(p) < ends[p] for p in parts):
            for batch in consumer.poll(timeout_ms=500).values():
                records = (Record(m.partition, m.offset, m.key, m.value) for m in batch)
                found += [record for record in records if keep(record)]
        return found
    finally:
        consumer.close()


def on_subject(topic: str, *subjects: str) -> list[Record]:
    """Les messages d'un sujet qui concernent ces carrefours, dans l'ordre de chaque partition."""
    wanted = {s.encode() for s in subjects}
    return sorted(
        read_topic(topic, lambda r: r.key in wanted), key=lambda r: (r.partition, r.offset)
    )


def producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        acks="all",
        linger_ms=0,
        request_timeout_ms=15000,
        max_block_ms=15000,
        client_id="novaria-reponse-tests",
    )


def send(kafka: KafkaProducer, event: dict, topic: str = "traffic.recommendations") -> None:
    kafka.send(topic, key=event["subject"].encode(), value=json.dumps(event).encode()).get(15)


# ------------------------------------------------------------------------------------ MongoDB
def database_name() -> str:
    return parse_uri(MONGO_URL)["database"]


def admin_logs():
    client = MongoClient(MONGO_ADMIN_URL, tz_aware=True, serverSelectionTimeoutMS=5000)
    return client, client[database_name()]["audit_logs"]


def audit_entries(*intersections: str) -> list[dict]:
    """Les entrées d'audit de ces carrefours, de la plus ancienne à la plus récente."""
    client, logs = admin_logs()
    try:
        query = {"details.intersection_id": {"$in": list(intersections)}}
        return list(logs.find(query).sort([("ts", 1), ("_id", 1)]))
    finally:
        client.close()


def erase(*intersections: str) -> None:
    """Efface les traces d'un essai (le compte du service, lui, ne peut pas supprimer)."""
    client, logs = admin_logs()
    try:
        logs.delete_many({"details.intersection_id": {"$in": list(intersections)}})
    finally:
        client.close()
