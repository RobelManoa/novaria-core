"""Publication sur Kafka (ADR-009) : un producteur, l'accusé du broker attendu pour chaque message.

Réglages du producteur et raison :
- `acks="all"` : le message n'est « publié » que quand le broker l'a écrit (avec un seul broker en
  local, c'est lui seul ; en production, tous les réplicas synchronisés) ;
- `enable_idempotence=True` : une nouvelle tentative interne du producteur ne duplique pas le
  message ;
- amorçage, requête et livraison sont bornés : sans courtier, la publication échoue en quelques
  secondes (503) au lieu d'attendre les 30 s et 120 s par défaut de kafka-python ;
- `linger_ms` court : les requêtes simultanées partent dans le même lot, sans retarder une requête
  seule ;
- le producteur est créé à la première publication, pas au démarrage : le service démarre et répond
  à sa sonde même si le broker est encore en train de démarrer ; tant qu'il manque, la publication
  lève `PublishFailed` (503 pour le client, qui renvoie).

**La création du producteur est une tentative unique, partagée.** `KafkaProducer(...)` amorce sa
connexion avant de rendre la main, au plus `bootstrap_timeout_ms` (mesuré : 3,0 s sur un port fermé
comme sur un écouteur qui ne répond pas). Si chaque requête la lançait sous un verrou, 50 requêtes
simultanées pendant une panne du broker attendraient 50 amorçages l'un après l'autre. Ici la
première lance la création dans un fil, les autres la rejoignent, et chacune n'attend que
`timeout_s` ; en cas d'échec la prochaine publication retente.
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout

from kafka import KafkaProducer
from kafka.errors import KafkaError

from app.services.ingestion import PublishFailed

logger = logging.getLogger("app.kafka")

LINGER_MS = 2
BOOTSTRAP_TIMEOUT_MS = 5000
REQUEST_TIMEOUT_MS = 5000


def _in_background(work: Callable[[], KafkaProducer]) -> Future:
    """Lance `work` dans un fil démon ; le résultat (ou l'erreur) arrive par le `Future`."""
    future: Future = Future()

    def run() -> None:
        try:
            future.set_result(work())
        except BaseException as error:  # noqa: BLE001 - l'erreur est rendue par le Future
            future.set_exception(error)

    threading.Thread(target=run, name="kafka-producer-creation", daemon=True).start()
    return future


class KafkaEventPublisher:
    def __init__(
        self,
        bootstrap_servers: str,
        *,
        timeout_s: float = 10.0,
        producer_factory: Callable[..., KafkaProducer] = KafkaProducer,
    ) -> None:
        self._servers = [s.strip() for s in bootstrap_servers.split(",") if s.strip()]
        self._timeout_s = timeout_s
        self._factory = producer_factory
        self._producer: KafkaProducer | None = None
        self._pending: Future | None = None
        self._lock = threading.Lock()

    def _create(self) -> KafkaProducer:
        timeout_ms = int(self._timeout_s * 1000)
        return self._factory(
            bootstrap_servers=self._servers,
            acks="all",
            enable_idempotence=True,
            linger_ms=LINGER_MS,
            bootstrap_timeout_ms=min(BOOTSTRAP_TIMEOUT_MS, timeout_ms),
            request_timeout_ms=min(REQUEST_TIMEOUT_MS, timeout_ms),
            delivery_timeout_ms=timeout_ms,
            max_block_ms=timeout_ms,
            client_id="novaria-collecte",
        )

    def _get(self) -> KafkaProducer:
        if self._producer is not None:
            return self._producer
        if not self._servers:
            raise PublishFailed("KAFKA_BOOTSTRAP_SERVERS n'est pas configuré")
        with self._lock:
            if self._producer is not None:
                return self._producer
            if self._pending is None:
                self._pending = _in_background(self._create)
            pending = self._pending
        try:
            producer = pending.result(timeout=self._timeout_s)
        except FutureTimeout as error:
            # La création continue en arrière-plan : le prochain appel reprendra ce même `Future`.
            logger.error("amorçage de Kafka trop long", extra={"fields": {"error": "KafkaTimeout"}})
            raise PublishFailed("KafkaTimeoutError (amorçage)") from error
        except KafkaError as error:
            with self._lock:
                if self._pending is pending:
                    self._pending = None  # la prochaine publication retente
            raise PublishFailed(type(error).__name__) from error
        with self._lock:
            if self._pending is pending:
                self._pending = None
                self._producer = producer
            return self._producer or producer

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        producer = self._get()
        try:
            future = producer.send(topic, key=key.encode("utf-8") if key else None, value=value)
            future.get(timeout=self._timeout_s)
        except KafkaError as error:
            # Le message de l'erreur n'est pas repris : seul son type est utile au diagnostic.
            logger.error(
                "publication échouée",
                extra={"fields": {"topic": topic, "error": type(error).__name__}},
            )
            raise PublishFailed(type(error).__name__) from error

    def close(self) -> None:
        with self._lock:
            producer, self._producer = self._producer, None
            pending, self._pending = self._pending, None
        if producer is not None:
            producer.close(timeout=self._timeout_s)
        if (
            pending is not None
        ):  # une création encore en cours : son résultat sera refermé à l'arrivée
            pending.add_done_callback(self._close_late)

    @staticmethod
    def _close_late(future: Future) -> None:
        if not future.cancelled() and future.exception() is None:
            future.result().close(timeout=1)
