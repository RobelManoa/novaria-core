"""Rejet d'un message : événement `errors.dlq` conforme, copie dans MongoDB `rejects`.

Partagé par le service de flux (`iot.raw`) et le pipeline d'écriture (`traffic.indicators`) : un
seul endroit décide de la forme d'un rejet, de son identifiant (partition et offset d'origine :
un rejeu retombe sur le même) et de son repli quand le rejet lui-même ne serait pas conforme.
"""

import json
import logging
from datetime import UTC, datetime

from pydantic import ValidationError

from app.schemas.events import RejectedEvent

from .model import Rejection
from .ports import EventPublisher, RejectArchive, StoreFailed

logger = logging.getLogger("app.flux")

TOPIC_ERRORS = "errors.dlq"
SERVICE = "traitement"
MAX_REASON = 2000


def utc_stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dumps(event: dict) -> bytes:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Rejector:
    def __init__(
        self, publisher: EventPublisher, archive: RejectArchive, source_topic: str
    ) -> None:
        self._publisher = publisher
        self._archive = archive
        self._source_topic = source_topic

    def reject(self, rejection: Rejection, now: datetime) -> str:
        """Publie et archive le rejet ; rend le code retenu (`PROCESSING_FAILED` au repli)."""
        stamp = utc_stamp(now)
        if rejection.partition is not None and rejection.offset is not None:
            identifier = (
                f"dlq:{SERVICE}:{self._source_topic}:{rejection.partition}:{rejection.offset}"
            )
        else:
            identifier = f"dlq:{SERVICE}:{self._source_topic}:{int(now.timestamp() * 1000)}"
        event = {
            "id": identifier,
            "source": SERVICE,
            "type": "novaria.error.rejected.v1",
            "time": stamp,
            "subject": rejection.intersection_id or "UNKNOWN",
            "schema_version": "1.0",
            "correlation_id": f"corr-{int(now.timestamp() * 1000)}",
            "domain": "error",
            "data": {
                "source_topic": self._source_topic,
                "rejected_at": stamp,
                "reason_code": rejection.reason_code,
                "reason": rejection.reason[:MAX_REASON] or "motif non précisé",
                "attempts": 1,
                "original_key": rejection.original_key,
                "intersection_id": rejection.intersection_id,
                "original_payload": rejection.original_payload,
            },
        }
        try:
            RejectedEvent.model_validate(event)  # le rejet respecte lui aussi le contrat
        except ValidationError:
            event = self._failed(event)
        self._publisher.publish(TOPIC_ERRORS, event["subject"], dumps(event))
        self._copy(event, now)
        return event["data"]["reason_code"]

    @staticmethod
    def _failed(event: dict) -> dict:
        """Rejet non conforme : remplacé par un échec de traitement, toujours conforme.

        Un message qui ferait échouer le rejet lui-même ne doit pas arrêter le service. Le code du
        motif d'origine est gardé dans le texte, la charge d'origine en texte borné.
        """
        data = event["data"]
        shown = str(data["reason_code"])[:60]
        return {
            **event,
            "subject": "UNKNOWN",
            "data": {
                **data,
                "reason_code": "PROCESSING_FAILED",
                "reason": f"rejet non conforme au contrat (motif {shown})",
                "original_key": None,
                "intersection_id": None,
                "original_payload": json.dumps(data["original_payload"], default=str)[:2000],
            },
        }

    def _copy(self, event: dict, now: datetime) -> None:
        data = event["data"]
        document = {
            "_id": event["id"],
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
            self._archive.insert(document)
        except StoreFailed:  # déjà sur errors.dlq : la copie manquante n'arrête pas le service
            logger.error("copie du rejet non écrite", extra={"fields": {"event_id": event["id"]}})
