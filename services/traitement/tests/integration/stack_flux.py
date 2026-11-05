"""Kafka, PostgreSQL et MongoDB réels pour les tests d'intégration du flux (MS-09).

Ignorés sans les variables `NOVARIA_TEST_FLUX_*` :
`python3 scripts/dev/dev.py test-integration --service flux` les fournit (projet Compose jetable,
migrations SQL appliquées, sujets créés, comptes de service réels `svc_traitement`).

- `..._POSTGRES_URL` / `..._MONGO_URL` : le compte `svc_traitement`, avec ses droits de production ;
- `..._POSTGRES_ADMIN_URL` / `..._MONGO_ADMIN_URL` : l'administrateur, pour relire et nettoyer.
"""

import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from pymongo import MongoClient
from sqlalchemy import create_engine, text

KAFKA = os.environ.get("NOVARIA_TEST_FLUX_KAFKA")
POSTGRES_URL = os.environ.get("NOVARIA_TEST_FLUX_POSTGRES_URL")
POSTGRES_ADMIN_URL = os.environ.get("NOVARIA_TEST_FLUX_POSTGRES_ADMIN_URL")
POSTGRES_READ_URL = os.environ.get("NOVARIA_TEST_FLUX_POSTGRES_READ_URL")
MONGO_URL = os.environ.get("NOVARIA_TEST_FLUX_MONGO_URL")
MONGO_ADMIN_URL = os.environ.get("NOVARIA_TEST_FLUX_MONGO_ADMIN_URL")

ALL = (KAFKA, POSTGRES_URL, POSTGRES_ADMIN_URL, POSTGRES_READ_URL, MONGO_URL, MONGO_ADMIN_URL)
needs_flux = pytest.mark.skipif(
    not all(ALL),
    reason="Kafka, PostgreSQL, MongoDB requis : dev.py test-integration --service flux",
)

for folder in Path(__file__).resolve().parents:  # validateur des contrats du dépôt
    if (folder / "contracts" / "topics.json").is_file():
        sys.path.insert(0, str(folder / "contracts"))
        break


def admin_engine():
    return create_engine(POSTGRES_ADMIN_URL)


def admin_mongo():
    return MongoClient(MONGO_ADMIN_URL, serverSelectionTimeoutMS=5000).get_default_database()


def produce(topic: str, items: list[tuple[bytes | None, bytes]]) -> list[tuple[int, int]]:
    """Publie dans l'ordre et rend (partition, offset) de chaque message."""
    producer = KafkaProducer(bootstrap_servers=[KAFKA], acks="all", linger_ms=0)
    try:
        sent = [producer.send(topic, key=key, value=value) for key, value in items]
        producer.flush(timeout=30)
        return [
            (meta.partition, meta.offset) for meta in (future.get(timeout=30) for future in sent)
        ]
    finally:
        producer.close()


def read_topic(topic: str) -> list[dict]:
    """Tout le contenu d'un sujet, depuis le début (messages JSON)."""
    consumer = KafkaConsumer(bootstrap_servers=[KAFKA], enable_auto_commit=False, group_id=None)
    try:
        partitions = [TopicPartition(topic, p) for p in consumer.partitions_for_topic(topic) or []]
        consumer.assign(partitions)
        consumer.seek_to_beginning(*partitions)
        ends = consumer.end_offsets(partitions)
        events: list[dict] = []
        deadline = time.monotonic() + 20
        while any(consumer.position(tp) < ends[tp] for tp in partitions):
            if time.monotonic() > deadline:
                break
            for batch in consumer.poll(timeout_ms=500).values():
                events.extend(json.loads(record.value) for record in batch)
        return events
    finally:
        consumer.close()


@dataclass
class Worker:
    group: str
    failure: list


def wait_for(
    condition: Callable[[], bool],
    timeout_s: float = 60.0,
    what: str = "la condition",
    worker: Worker | None = None,
) -> None:
    """Attend `condition` ; si le service plante entre-temps, relève sa vraie panne aussitôt."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if worker is not None and worker.failure:
            raise worker.failure[0]
        if condition():
            return
        time.sleep(0.5)
    raise AssertionError(f"délai dépassé ({timeout_s:.0f} s) en attendant {what}")


def committed_offsets(group: str, topic: str) -> dict[int, int | None]:
    consumer = KafkaConsumer(bootstrap_servers=[KAFKA], group_id=group, enable_auto_commit=False)
    try:
        partitions = [TopicPartition(topic, p) for p in consumer.partitions_for_topic(topic) or []]
        return {tp.partition: consumer.committed(tp) for tp in partitions}
    finally:
        consumer.close()


@contextmanager
def flux_worker(group: str | None = None, replay: bool = False) -> Iterator[Worker]:
    """Lance le vrai service (adaptateurs réels) dans un fil ; relève sa panne à la sortie."""
    from app.flux.adapters.kafka_io import KafkaPublisher, KafkaSource
    from app.flux.adapters.mongo_store import MongoStore
    from app.flux.adapters.warehouse import Warehouse
    from app.flux.processor import Processor
    from app.flux.runner import run

    group = group or f"it-flux-{uuid.uuid4().hex[:8]}"
    warehouse, mongo = Warehouse(POSTGRES_URL), MongoStore(MONGO_URL)
    publisher = KafkaPublisher(KAFKA)
    processor = Processor(
        warehouse.load_referential(), publisher, mongo, warehouse, mongo, replay=replay
    )
    source = KafkaSource(KAFKA, "iot.raw", group, max_records=200)
    stop, failure = threading.Event(), []

    def work() -> None:
        try:
            run(processor, source, stop, poll_timeout_ms=200)
        except Exception as error:  # noqa: BLE001 - relevée dans le fil du test
            failure.append(error)

    thread = threading.Thread(target=work, name="flux-worker", daemon=True)
    thread.start()
    try:
        yield Worker(group, failure)
    finally:
        stop.set()
        thread.join(timeout=30)
        source.close()
        publisher.close()
        mongo.close()
        warehouse.close()
        if failure:
            raise failure[0]


def day_start(day: int) -> datetime:
    """08:00 UTC d'un jour propre au test (septembre 2026) : les compteurs ne se mêlent pas."""
    return datetime(2026, 9, day, 8, 0, tzinfo=UTC)


def clean_traces(run_ids: list[str], day: int) -> None:
    """Efface ce qu'un test a écrit (les comptes de service ne peuvent pas supprimer)."""
    with admin_engine().begin() as connection:
        connection.execute(
            text("DELETE FROM dwh.fact_congestion_episode WHERE run_id = ANY(:ids)"),
            {"ids": run_ids},
        )
    base = admin_mongo()
    start = day_start(day)
    base.processing_stats.delete_many(
        {"window_start": {"$gte": start, "$lt": start.replace(hour=23)}}
    )
    base.rejects.delete_many({"original_payload.data.provenance.run_id": {"$in": run_ids}})
    for run_id in run_ids:  # un message illisible est archivé en texte : le run s'y lit
        base.rejects.delete_many({"original_payload": {"$regex": run_id}})


def produce_timed(topic: str, key: bytes | None, value: bytes) -> float:
    """Publie un message et rend l'instant (horloge monotone) où le broker l'a accusé."""
    producer = KafkaProducer(bootstrap_servers=[KAFKA], acks="all", linger_ms=0)
    try:
        producer.send(topic, key=key, value=value).get(timeout=30)
        return time.perf_counter()
    finally:
        producer.close()


class Probe:
    """Lecteur posé à la fin d'un sujet avant l'action mesurée ; rend l'instant d'arrivée."""

    def __init__(self, topic: str) -> None:
        self._consumer = KafkaConsumer(
            bootstrap_servers=[KAFKA], enable_auto_commit=False, group_id=None
        )
        partitions = [
            TopicPartition(topic, p) for p in self._consumer.partitions_for_topic(topic) or []
        ]
        self._consumer.assign(partitions)
        self._consumer.seek_to_end(*partitions)
        for partition in partitions:
            self._consumer.position(partition)  # matérialise la position avant de rendre la main

    def __enter__(self) -> "Probe":
        return self

    def __exit__(self, *exc) -> None:
        self._consumer.close()

    def wait_for(
        self, predicate: Callable[[dict], bool], timeout_s: float, worker: "Worker | None" = None
    ) -> tuple[dict, float]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if worker is not None and worker.failure:
                raise worker.failure[0]
            for batch in self._consumer.poll(timeout_ms=20).values():
                for record in batch:
                    arrived = time.perf_counter()
                    event = json.loads(record.value)
                    if predicate(event):
                        return event, arrived
        raise AssertionError(f"aucun événement attendu en {timeout_s:.0f} s")


def stats_total(kind: str, name: str, day: int) -> int:
    """Somme d'un compteur de `processing_stats` sur les documents du jour d'essai."""
    start = day_start(day)
    documents = admin_mongo().processing_stats.find(
        {"kind": kind, "window_start": {"$gte": start, "$lt": start + timedelta(hours=2)}}
    )
    return sum(document["values"].get(name, 0) for document in documents)


@contextmanager
def pipeline_worker(group: str | None = None) -> Iterator[Worker]:
    """Lance le vrai pipeline d'écriture (adaptateurs réels, compte svc_traitement) dans un fil."""
    from app.flux.adapters.kafka_io import KafkaPublisher, KafkaSource
    from app.flux.adapters.mongo_store import MongoStore
    from app.flux.runner import run
    from app.pipeline.adapters.postgres import WarehouseWriter
    from app.pipeline.processor import Pipeline
    from app.pipeline.recommender import Recommender

    group = group or f"it-pipeline-{uuid.uuid4().hex[:8]}"
    writer, mongo = WarehouseWriter(POSTGRES_URL), MongoStore(MONGO_URL)
    publisher = KafkaPublisher(KAFKA)
    pipeline = Pipeline(writer, Recommender(writer.load_plan_reference()), publisher, mongo, mongo)
    source = KafkaSource(KAFKA, "traffic.indicators", group, max_records=200)
    stop, failure = threading.Event(), []

    def work() -> None:
        try:
            run(pipeline, source, stop, poll_timeout_ms=200)
        except Exception as error:  # noqa: BLE001 - relevée dans le fil du test
            failure.append(error)

    thread = threading.Thread(target=work, name="pipeline-worker", daemon=True)
    thread.start()
    try:
        yield Worker(group, failure)
    finally:
        stop.set()
        thread.join(timeout=30)
        source.close()
        publisher.close()
        mongo.close()
        writer.close()
        if failure:
            raise failure[0]


def clean_warehouse(run_ids: list[str]) -> None:
    """Efface faits et exécutions d'un test (un compte de service ne peut pas tout supprimer)."""
    with admin_engine().begin() as connection:
        for statement in (
            "DELETE FROM dwh.fact_traffic_window WHERE run_id = ANY(:ids)",
            "DELETE FROM dwh.fact_congestion_episode WHERE run_id = ANY(:ids)",
            "DELETE FROM dwh.dim_run WHERE run_id = ANY(:ids)",
        ):
            connection.execute(text(statement), {"ids": run_ids})
