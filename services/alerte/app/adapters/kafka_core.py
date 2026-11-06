"""Noyau Kafka commun aux services qui lisent en groupe et publient (alerte, réponse) : ADR-009.

**Producteur** : `acks="all"` et idempotence, comme la collecte et le traitement. `flush` attend les
accusés de tous les messages envoyés : un événement n'est retiré d'une file qu'après cet accusé.

**Consommateur** : lecture en groupe, validation **manuelle** des offsets (`enable_auto_commit`
faux) : un offset n'est validé qu'une fois le message traité et ses événements partis (livraison au
moins une fois). Une seule instance lit les partitions : l'état des services est en mémoire.

Copie identique dans les services qui s'en servent : `scripts/dev/test_gabarit.py` (CODE_PARTAGE).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from kafka.structs import OffsetAndMetadata, TopicPartition

from app.services.ports import PublishFailed

logger = logging.getLogger("app.kafka")

BOOTSTRAP_TIMEOUT_MS = 5000
REQUEST_TIMEOUT_MS = 5000
CONSUMER_REQUEST_TIMEOUT_MS = 30000  # doit dépasser le délai de session du groupe
UNASSIGNED_LIMIT_S = 60  # sans partition affectée plus longtemps, la lecture est relancée


class NoPartitionsAssigned(RuntimeError):
    """Le groupe n'a affecté aucune partition à ce lecteur : il ne lirait jamais rien.

    Arrive quand le chef de groupe répartit les partitions avant d'avoir les métadonnées du sujet
    (`kafka-python` journalise « No partition metadata for topic »). Plutôt que de rester vivant et
    muet, l'appelant s'arrête ou relance la lecture avec un nouveau consommateur.
    """


def servers(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Record:
    key: bytes | None
    value: bytes
    partition: int
    offset: int


class KafkaPublisher:
    def __init__(
        self,
        bootstrap_servers: str,
        *,
        timeout_s: float = 10.0,
        client_id: str = "novaria",
        producer_factory: Callable[..., KafkaProducer] = KafkaProducer,
    ) -> None:
        self._servers = servers(bootstrap_servers)
        self._timeout_s = timeout_s
        self._client_id = client_id
        self._factory = producer_factory
        self._producer: KafkaProducer | None = None
        self._pending: list = []

    def _get(self) -> KafkaProducer:
        if self._producer is None:
            if not self._servers:
                raise PublishFailed("KAFKA_BOOTSTRAP_SERVERS n'est pas configuré")
            timeout_ms = int(self._timeout_s * 1000)
            try:
                self._producer = self._factory(
                    bootstrap_servers=self._servers,
                    acks="all",
                    enable_idempotence=True,
                    linger_ms=0,  # un événement part tout de suite : on mesure sa latence
                    bootstrap_timeout_ms=min(BOOTSTRAP_TIMEOUT_MS, timeout_ms),
                    request_timeout_ms=min(REQUEST_TIMEOUT_MS, timeout_ms // 2),
                    delivery_timeout_ms=timeout_ms,
                    max_block_ms=timeout_ms,
                    client_id=self._client_id,
                )
            except KafkaError as error:
                raise PublishFailed(type(error).__name__) from error
        return self._producer

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        producer = self._get()
        try:
            future = producer.send(topic, key=key.encode("utf-8") if key else None, value=value)
        except KafkaError as error:
            logger.error(
                "publication refusée",
                extra={"fields": {"topic": topic, "error": type(error).__name__}},
            )
            raise PublishFailed(type(error).__name__) from error
        self._pending.append(future)

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        if not pending:
            return
        try:
            self._get().flush(timeout=self._timeout_s)
            for future in pending:
                future.get(timeout=self._timeout_s)
        except KafkaError as error:
            logger.error(
                "accusé de réception manquant", extra={"fields": {"error": type(error).__name__}}
            )
            raise PublishFailed(type(error).__name__) from error

    def close(self) -> None:
        producer, self._producer = self._producer, None
        if producer is not None:
            producer.close(timeout=self._timeout_s)


class KafkaSource:
    """Lecture en groupe, validation manuelle : `poll` puis `commit` (prochain offset à lire)."""

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        *,
        max_records: int = 500,
        auto_offset_reset: str = "earliest",
        unassigned_limit_s: float = UNASSIGNED_LIMIT_S,
        client_id: str = "novaria",
        consumer_factory: Callable[..., KafkaConsumer] = KafkaConsumer,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._topic = topic
        self._max_records = max_records
        self._unassigned_limit_s = unassigned_limit_s
        self._monotonic = monotonic
        self._unassigned_since: float | None = None
        self._consumer = consumer_factory(
            topic,
            bootstrap_servers=servers(bootstrap_servers),
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset=auto_offset_reset,
            bootstrap_timeout_ms=BOOTSTRAP_TIMEOUT_MS,
            request_timeout_ms=CONSUMER_REQUEST_TIMEOUT_MS,
            client_id=client_id,
        )
        # Les métadonnées du sujet avant la première jointure : un chef de groupe qui ne les a pas
        # n'affecte aucune partition.
        self._consumer.partitions_for_topic(topic)

    def _check_assignment(self) -> None:
        if self._consumer.assignment():
            self._unassigned_since = None
            return
        now = self._monotonic()
        if self._unassigned_since is None:
            self._unassigned_since = now
        elif now - self._unassigned_since >= self._unassigned_limit_s:
            raise NoPartitionsAssigned(self._topic)

    def poll(self, timeout_ms: int = 1000) -> list[Record]:
        batches = self._consumer.poll(timeout_ms=timeout_ms, max_records=self._max_records)
        self._check_assignment()
        records = [
            Record(r.key, r.value if r.value is not None else b"", r.partition, r.offset)
            for partition_records in batches.values()
            for r in partition_records
        ]
        return sorted(records, key=lambda r: (r.partition, r.offset))

    def commit(self, offsets: dict[int, int]) -> None:
        if not offsets:
            return
        self._consumer.commit(
            {
                TopicPartition(self._topic, partition): OffsetAndMetadata(offset, "", -1)
                for partition, offset in offsets.items()
            }
        )

    def close(self) -> None:
        self._consumer.close()
