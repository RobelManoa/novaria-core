"""Kafka côté alerte : noyau commun (`kafka_core.py`) et lecteur de `alerts.events` (diffusion).

**Lecteur de `alerts.events`** (diffusion en direct) : sans groupe, partitions assignées à la main
et lecture depuis la fin. Chaque instance de l'API reçoit **tous** les événements, ce que veut un
flux diffusé à ses clients ; elle ne garde aucun offset (un client qui se reconnecte relit la
liste des alertes par l'API, il ne rejoue pas le sujet).
"""

import logging
import threading
import time
from collections.abc import Callable

from kafka import KafkaConsumer
from kafka.structs import TopicPartition

from app.adapters.kafka_core import (
    BOOTSTRAP_TIMEOUT_MS,
    CONSUMER_REQUEST_TIMEOUT_MS,
    KafkaPublisher,
    KafkaSource,
    NoPartitionsAssigned,
    Record,
    servers,
)

__all__ = [
    "EventsReader",
    "KafkaPublisher",
    "KafkaSource",
    "NoPartitionsAssigned",
    "Record",
    "servers",
]

logger = logging.getLogger("app.kafka")

PARTITIONS_WAIT_S = 30  # attente des métadonnées du sujet avant d'abandonner la tentative


class EventsReader:
    """Lit `alerts.events` depuis la fin et passe chaque message à `on_message` (fil de fond).

    Une panne du broker ne tue pas le fil : il journalise, attend, et se reconnecte.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        on_message: Callable[[bytes], None],
        *,
        retry_s: float = 2.0,
        consumer_factory: Callable[..., KafkaConsumer] = KafkaConsumer,
    ) -> None:
        self._servers = servers(bootstrap_servers)
        self._topic = topic
        self._on_message = on_message
        self._retry_s = retry_s
        self._factory = consumer_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.ready = threading.Event()  # levé quand les partitions sont assignées et positionnées

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="alerts-events-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._read()
            except Exception as error:  # noqa: BLE001 - le fil ne doit jamais mourir
                logger.error(
                    "lecture de alerts.events interrompue, nouvelle tentative",
                    extra={"fields": {"error": type(error).__name__}},
                )
            self.ready.clear()
            self._stop.wait(self._retry_s)

    def _read(self) -> None:
        consumer = self._factory(
            bootstrap_servers=self._servers,
            enable_auto_commit=False,
            group_id=None,
            bootstrap_timeout_ms=BOOTSTRAP_TIMEOUT_MS,
            request_timeout_ms=CONSUMER_REQUEST_TIMEOUT_MS,
            client_id="novaria-alerte-sse",
        )
        try:
            partitions = self._partitions(consumer)
            consumer.assign(partitions)
            consumer.seek_to_end(*partitions)
            for partition in partitions:
                consumer.position(partition)  # force la résolution de la fin avant de dire « prêt »
            self.ready.set()
            while not self._stop.is_set():
                for batch in consumer.poll(timeout_ms=500).values():
                    for message in batch:
                        self._on_message(message.value)
        finally:
            consumer.close()

    def _partitions(self, consumer: KafkaConsumer) -> list[TopicPartition]:
        deadline = time.monotonic() + PARTITIONS_WAIT_S
        while time.monotonic() < deadline and not self._stop.is_set():
            found = consumer.partitions_for_topic(self._topic)
            if found:
                return [TopicPartition(self._topic, p) for p in sorted(found)]
            time.sleep(0.2)
        raise TimeoutError(f"sujet {self._topic} introuvable")
