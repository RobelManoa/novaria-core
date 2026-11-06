"""Kafka : lire `traffic.recommendations`, publier `signal.status` et `errors.dlq` (ADR-009).

**Producteur** : `acks="all"` et idempotence. `flush` attend l'accusé du broker pour tout ce qui a
été envoyé : un événement n'est retiré de la file d'envoi qu'après cet accusé.

**Consommateur** : groupe `reponse`, validation **manuelle** des offsets. Un offset n'est validé
qu'une fois le message traité et ses événements partis (livraison au moins une fois ; rejouer une
recommandation est sans effet). Une seule instance lit les partitions : l'état des feux est en
mémoire.
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
    """Le groupe n'a affecté aucune partition : le lecteur ne lirait jamais rien.

    Un chef de groupe qui n'a pas encore les métadonnées du sujet n'en affecte aucune
    (`kafka-python` journalise « No partition metadata for topic »). Plutôt que de rester vivant et
    muet, la lecture est relancée avec un nouveau consommateur.
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
        producer_factory: Callable[..., KafkaProducer] = KafkaProducer,
    ) -> None:
        self._servers = servers(bootstrap_servers)
        self._timeout_s = timeout_s
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
                    linger_ms=0,  # un changement d'état des feux part tout de suite
                    bootstrap_timeout_ms=min(BOOTSTRAP_TIMEOUT_MS, timeout_ms),
                    request_timeout_ms=min(REQUEST_TIMEOUT_MS, timeout_ms // 2),
                    delivery_timeout_ms=timeout_ms,
                    max_block_ms=timeout_ms,
                    client_id="novaria-reponse",
                )
            except KafkaError as error:
                raise PublishFailed(type(error).__name__) from error
        return self._producer

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        producer = self._get()
        try:
            future = producer.send(topic, key=key.encode("utf-8") if key else None, value=value)
        except KafkaError as error:
            raise PublishFailed(type(error).__name__) from error
        self._pending.append(future)

    def flush(self) -> None:
        """Attend l'accusé de tout ce qui a été envoyé ; ce qui n'est pas accusé est à renvoyer."""
        pending, self._pending = self._pending, []
        if not pending:
            return
        try:
            self._get().flush(timeout=self._timeout_s)
            for future in pending:
                future.get(timeout=self._timeout_s)
        except KafkaError as error:
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
        max_records: int = 200,
        unassigned_limit_s: float = UNASSIGNED_LIMIT_S,
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
            # Un groupe neuf lit depuis le début : une recommandation encore valable n'est pas
            # perdue. Les plus anciennes sont écartées par le contrôleur (identifiant, instant).
            auto_offset_reset="earliest",
            bootstrap_timeout_ms=BOOTSTRAP_TIMEOUT_MS,
            request_timeout_ms=CONSUMER_REQUEST_TIMEOUT_MS,
            client_id="novaria-reponse",
        )
        # Les métadonnées du sujet avant la première jointure (voir `NoPartitionsAssigned`).
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

    def poll(self, timeout_ms: int = 500) -> list[Record]:
        batches = self._consumer.poll(timeout_ms=timeout_ms, max_records=self._max_records)
        self._check_assignment()
        records = [
            Record(r.key, r.value if r.value is not None else b"", r.partition, r.offset)
            for partition_records in batches.values()
            for r in partition_records
        ]
        return sorted(records, key=lambda r: (r.partition, r.offset))

    def commit(self, offsets: dict[int, int]) -> None:
        if offsets:
            self._consumer.commit(
                {
                    TopicPartition(self._topic, partition): OffsetAndMetadata(offset, "", -1)
                    for partition, offset in offsets.items()
                }
            )

    def close(self) -> None:
        self._consumer.close()
