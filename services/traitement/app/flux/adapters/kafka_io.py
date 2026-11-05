"""Kafka : publication des indicateurs et des rejets, lecture de `iot.raw` en groupe (ADR-009).

Producteur : `acks="all"` et idempotence (une nouvelle tentative interne ne duplique pas), comme la
collecte. Les messages partent en lot ; `flush` attend les accusés de tous : le processeur n'appelle
`flush` qu'avant de valider un offset, jamais message par message.

Consommateur : groupe `traitement-flux`, **validation manuelle** (`enable_auto_commit=False`) : un
offset n'est validé qu'après publication accusée (livraison au moins une fois). Une seule instance
lit les trois partitions : les fenêtres sont en mémoire, un second lecteur du même groupe se
partagerait les partitions et ne verrait plus que des morceaux de fenêtre.
"""

import logging
from collections.abc import Callable

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from kafka.structs import OffsetAndMetadata, TopicPartition

from app.flux.ports import PublishFailed, Record

logger = logging.getLogger("app.flux.kafka")

BOOTSTRAP_TIMEOUT_MS = 5000
REQUEST_TIMEOUT_MS = 5000  # kafka-python : délai de livraison > linger + délai de requête
CONSUMER_REQUEST_TIMEOUT_MS = 30000  # doit dépasser le délai de session du groupe
MAX_PENDING = 2000  # au-delà, `publish` attend les accusés avant de continuer


def _servers(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class KafkaPublisher:
    def __init__(
        self,
        bootstrap_servers: str,
        *,
        timeout_s: float = 10.0,
        producer_factory: Callable[..., KafkaProducer] = KafkaProducer,
    ) -> None:
        self._servers = _servers(bootstrap_servers)
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
                    linger_ms=20,
                    bootstrap_timeout_ms=min(BOOTSTRAP_TIMEOUT_MS, timeout_ms),
                    request_timeout_ms=min(REQUEST_TIMEOUT_MS, timeout_ms // 2),
                    delivery_timeout_ms=timeout_ms,
                    max_block_ms=timeout_ms,
                    client_id="novaria-traitement-flux",
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
        self._pending.append((topic, future))
        if len(self._pending) >= MAX_PENDING:
            self.flush()

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        if not pending:
            return
        try:
            self._get().flush(timeout=self._timeout_s)
            for _topic, future in pending:
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
    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        *,
        max_records: int = 500,
        consumer_factory: Callable[..., KafkaConsumer] = KafkaConsumer,
    ) -> None:
        self._topic = topic
        self._max_records = max_records
        self._consumer = consumer_factory(
            topic,
            bootstrap_servers=_servers(bootstrap_servers),
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            bootstrap_timeout_ms=BOOTSTRAP_TIMEOUT_MS,
            request_timeout_ms=CONSUMER_REQUEST_TIMEOUT_MS,
            client_id="novaria-traitement-flux",
        )

    def poll(self, timeout_ms: int = 1000) -> list[Record]:
        batches = self._consumer.poll(timeout_ms=timeout_ms, max_records=self._max_records)
        records = [
            Record(r.key, r.value if r.value is not None else b"", r.partition, r.offset)
            for partition_records in batches.values()
            for r in partition_records
        ]
        return sorted(records, key=lambda r: (r.partition, r.offset))

    def commit(self, offsets: dict[int, int]) -> None:
        """Valide « prochain message à lire » pour chaque partition."""
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
