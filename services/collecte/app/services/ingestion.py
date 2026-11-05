"""Réception d'une mesure : validation, publication, copie brute, idempotence (MS-08).

Une mesure reçue a **une** de ces trois issues, et aucune autre :

- `ACCEPTED` : conforme et nouvelle ; publiée sur `iot.raw` (clé = carrefour), copie brute dans
  `raw_events`
- `DUPLICATE` : conforme, `id` déjà reçu ; **ignorée** : ni publiée, ni stockée une seconde fois ;
  journalisée
- `REJECTED` : hors contrat ; **jamais** sur `iot.raw` ; un message `novaria.error.rejected.v1` avec
  le motif part sur `errors.dlq`, copie dans `rejects`

Sans état entre deux requêtes : tout ce qui survit à une requête est dans Kafka et MongoDB. La
mémoire du processus ne sert qu'à faire passer l'une après l'autre deux requêtes simultanées de même
`id` (verrous par `id`, détruits à la fin de l'appel).

Ordre des opérations pour une mesure nouvelle, et pourquoi :
1. chercher l'`id` dans `raw_events` (index unique `uniq_event_id`) : déjà là, doublon ;
2. publier sur `iot.raw` et **attendre l'accusé du broker** (`acks=all`) ;
3. écrire la copie brute dans `raw_events`. Publier avant de stocker, jamais l'inverse : le rôle
   MongoDB de la collecte ne peut ni modifier ni supprimer (`find` et `insert` seulement, ADR-024),
   donc un `id` stocké mais jamais publié ne pourrait plus être réparé, et la mesure serait perdue.
   Dans le sens choisi, la panne d'une étape ne perd rien : le client reçoit 503 et renvoie la
   mesure. Le seul défaut possible est une double publication (la mesure est publiée, MongoDB tombe
   avant l'écriture, le client renvoie) ; le traitement dédoublonne par `id` (DQ-03). C'est
   l'hypothèse « au moins une fois » de l'ADR-009.
"""

import json
import logging
import secrets
import threading
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from app.schemas.events import RejectedEvent
from app.services.validation import SOURCE_TOPIC, Rejection, Valid, parse_utc, validate_measurement

logger = logging.getLogger("app.ingestion")

TOPIC_RAW = SOURCE_TOPIC
TOPIC_ERRORS = "errors.dlq"
SERVICE = "collecte"
LOCK_STRIPES = 256


class PublishFailed(Exception):
    """Le broker n'a pas accusé réception (indisponible, délai dépassé, message refusé)."""


class StoreFailed(Exception):
    """MongoDB n'a pas répondu ou a refusé l'écriture."""


class EventPublisher(Protocol):
    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        """Rend quand le broker a accusé réception ; lève `PublishFailed` sinon."""


class RawEventStore(Protocol):
    def exists(self, event_id: str) -> bool: ...

    def insert(self, document: dict) -> bool:
        """`False` si l'`id` existe déjà (index unique) ; `StoreFailed` sur toute autre panne."""


class RejectArchive(Protocol):
    def insert(self, document: dict) -> None: ...


class Outcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Receipt:
    outcome: Outcome
    event_id: str | None  # `id` du message reçu, s'il en a un
    rejection: Rejection | None = None


class StripedLocks:
    """Un nombre fixe de verrous, choisis par l'`id` : deux requêtes de même `id` se suivent."""

    def __init__(self, stripes: int = LOCK_STRIPES) -> None:
        self._locks = [threading.Lock() for _ in range(stripes)]

    def __call__(self, key: str) -> threading.Lock:
        return self._locks[zlib.crc32(key.encode("utf-8")) % len(self._locks)]


def dumps(event: dict) -> bytes:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def utc_stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class IngestionService:
    def __init__(
        self,
        publisher: EventPublisher,
        raw_events: RawEventStore,
        rejects: RejectArchive,
        *,
        max_bytes: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        locks: Callable[[str], threading.Lock] | None = None,
    ) -> None:
        self._publisher = publisher
        self._raw_events = raw_events
        self._rejects = rejects
        self._max_bytes = max_bytes
        self._clock = clock
        self._locks = locks or StripedLocks()

    def receive(self, body: bytes, *, correlation_id: str | None = None) -> Receipt:
        """Traite un message reçu (octets). Lève `PublishFailed` ou `StoreFailed` : rien n'est
        perdu,
        l'appelant répond « indisponible » et l'émetteur renvoie le message."""
        result = validate_measurement(body, max_bytes=self._max_bytes)
        if isinstance(result, Rejection):
            return self._reject(result, correlation_id)
        return self._accept(result)

    # ------------------------------------------------------------------------------- mesure valide
    def _accept(self, valid: Valid) -> Receipt:
        event_id = valid.event_id
        with self._locks(event_id):
            if self._raw_events.exists(event_id):
                self._duplicate(event_id)
                return Receipt(Outcome.DUPLICATE, event_id)
            self._publisher.publish(TOPIC_RAW, valid.event["subject"], dumps(valid.event))
            document = {
                **valid.event,
                "time": parse_utc(valid.event["time"]),
                "received_at": self._clock(),
            }
            if not self._raw_events.insert(document):
                # Une autre instance a publié et stocké cet `id` entre la recherche et l'écriture.
                logger.warning(
                    "double publication évitée de justesse",
                    extra={"fields": {"event_id": event_id}},
                )
                self._duplicate(event_id)
                return Receipt(Outcome.DUPLICATE, event_id)
        logger.info("mesure acceptée", extra={"fields": {"event_id": event_id, "topic": TOPIC_RAW}})
        return Receipt(Outcome.ACCEPTED, event_id)

    @staticmethod
    def _duplicate(event_id: str) -> None:
        logger.info(
            "doublon ignoré", extra={"fields": {"event_id": event_id, "counter": "duplicates"}}
        )

    # ------------------------------------------------------------------------------ mesure rejetée
    def _reject(self, rejection: Rejection, correlation_id: str | None) -> Receipt:
        now = self._clock()
        stamp = utc_stamp(now)
        event = {
            "id": f"dlq:{SERVICE}:{TOPIC_RAW}:{int(now.timestamp() * 1000)}:{secrets.token_hex(4)}",
            "source": SERVICE,
            "type": "novaria.error.rejected.v1",
            "time": stamp,
            "subject": rejection.intersection_id or "UNKNOWN",
            "schema_version": "1.0",
            "correlation_id": correlation_id or f"corr-{int(now.timestamp() * 1000)}",
            "domain": "error",
            "data": {
                "source_topic": TOPIC_RAW,
                "rejected_at": stamp,
                "reason_code": rejection.reason_code,
                "reason": rejection.reason,
                "attempts": 1,
                "original_key": rejection.original_key,
                "intersection_id": rejection.intersection_id,
                "original_payload": rejection.original_payload,
            },
        }
        RejectedEvent.model_validate(event)  # le message d'erreur respecte lui aussi le contrat
        self._publisher.publish(TOPIC_ERRORS, event["subject"], dumps(event))
        self._archive(event, now)
        original_id = (
            rejection.original_payload.get("id")
            if isinstance(rejection.original_payload, dict)
            else None
        )
        logger.info(
            "mesure rejetée",
            extra={
                "fields": {
                    "reason_code": rejection.reason_code,
                    "topic": TOPIC_ERRORS,
                    "counter": "rejects",
                }
            },
        )
        return Receipt(
            Outcome.REJECTED, original_id if isinstance(original_id, str) else None, rejection
        )

    def _archive(self, event: dict, now: datetime) -> None:
        """Copie dans `rejects`. Déjà sur `errors.dlq` : une panne ici n'est pas fatale."""
        data = event["data"]
        document = {
            "source_topic": data["source_topic"],
            "rejected_at": now,
            "reason": data["reason"],
            "reason_code": data["reason_code"],
            "service": SERVICE,
            "attempts": data["attempts"],
            "original_key": data["original_key"],
            "intersection_id": data["intersection_id"],
            "correlation_id": event["correlation_id"],
            "event_id": event["id"],
            "original_payload": data["original_payload"],
        }
        try:
            self._rejects.insert(document)
        except StoreFailed:
            logger.error(
                "copie du rejet non écrite dans rejects",
                extra={"fields": {"event_id": event["id"]}},
            )
