"""Kafka et PostgreSQL réels pour les tests d'intégration de l'alerte (MS-11).

Ignorés sans `NOVARIA_TEST_KAFKA_BOOTSTRAP` et `NOVARIA_TEST_ALERTE_POSTGRES_URL` :
`python scripts/dev/dev.py test-integration --service alerte` les fournit (projet Compose jetable,
migrations appliquées par `db-migrate`, sujets créés par `infra/kafka/init-topics.sh`, compte de
service `svc_alerte` aux droits de production).
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import psycopg
import pytest
from kafka import KafkaConsumer, KafkaProducer, TopicPartition

BOOTSTRAP = os.environ.get("NOVARIA_TEST_KAFKA_BOOTSTRAP")
PG_URL = os.environ.get("NOVARIA_TEST_ALERTE_POSTGRES_URL")  # compte svc_alerte
PG_ADMIN_URL = os.environ.get("NOVARIA_TEST_ALERTE_POSTGRES_ADMIN_URL")  # relit et nettoie

needs_stack = pytest.mark.skipif(
    not (BOOTSTRAP and PG_URL and PG_ADMIN_URL),
    reason="Kafka et PostgreSQL requis (NOVARIA_TEST_KAFKA_BOOTSTRAP et NOVARIA_TEST_ALERTE_*)",
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
    step: float = 0.02,
    why: Callable[[], str] | None = None,
):
    """Rend la valeur (vraie) de `condition` dès qu'elle l'est ; `AssertionError` après `seconds`.

    `why` dit, à l'échec, ce qu'on a vu à la place : un délai dépassé sans explication est vain.
    """
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
        client_id="novaria-alerte-tests",
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


def producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        acks="all",
        linger_ms=0,
        request_timeout_ms=15000,
        max_block_ms=15000,
        client_id="novaria-alerte-tests",
    )


def send(kafka: KafkaProducer, event: dict, topic: str = "traffic.indicators") -> float:
    """Envoie un événement et rend l'instant (horloge monotone) où le broker a accusé réception."""
    kafka.send(topic, key=event["subject"].encode(), value=json.dumps(event).encode()).get(15)
    return time.perf_counter()


# ------------------------------------------------------------------------------------ PostgreSQL
def admin() -> psycopg.Connection:
    return psycopg.connect(PG_ADMIN_URL, autocommit=True, row_factory=psycopg.rows.dict_row)


def rows(sql: str, *params) -> list[dict]:
    with admin() as connection:
        return connection.execute(sql, params).fetchall()


def erase(run_id: str) -> None:
    """Efface les traces d'un essai : alertes (et leur historique, en cascade) et boîte d'envoi."""
    with admin() as connection:
        connection.execute("DELETE FROM alertes.alert WHERE run_id = %s", (run_id,))
        connection.execute(
            "DELETE FROM alertes.outbox_event WHERE payload->'data'->'provenance'->>'run_id' = %s",
            (run_id,),
        )
