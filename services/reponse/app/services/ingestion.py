"""Un message de `traffic.recommendations` : valider, puis le soumettre aux garde-fous (MS-12).

Un message hors contrat n'arrête rien : il part sur `errors.dlq` avec son motif. Une recommandation
valable mais dangereuse n'est pas une erreur du bus : le contrôleur la refuse, le dit sur
`signal.status` et la journalise. Rejouer une recommandation est sans effet (identifiant retenu).
"""

import json
import logging
import re
import secrets
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.core.config import TOPIC_ERRORS, TOPIC_RECOMMENDATIONS
from app.domain.model import utc_stamp, utcnow
from app.schemas.events import RecommendationEvent, RejectedEvent
from app.services.events import SOURCE, dumps
from app.services.outbox import Outbox, Outgoing
from app.services.signals import Clock, SignalService

logger = logging.getLogger("app.ingestion")

RECOMMENDATION_TYPE = "novaria.traffic.recommendation.v1"
MAX_TEXT = 20000  # un message illisible est conservé sous forme de texte, tronqué
INTERSECTION = re.compile(r"INT_[0-9]{2,}")


def _refuse_constant(name: str) -> None:
    raise ValueError(f"constante JSON non permise : {name}")  # NaN, Infinity : pas du JSON strict


def contract_reason(error: ValidationError) -> str:
    """Le premier défaut, au chemin et au message de la bibliothèque, sans la valeur refusée."""
    first = error.errors(include_input=False)[0]
    path = "/".join(str(part) for part in first["loc"])
    more = len(error.errors()) - 1
    return f"{path} : {first['msg']}" + (f" (et {more} autre(s))" if more else "")


class RecommendationHandler:
    def __init__(self, service: SignalService, outbox: Outbox, *, clock: Clock = utcnow) -> None:
        self._service = service
        self._outbox = outbox
        self._clock = clock

    def handle(self, raw: bytes, key: bytes | None = None) -> str:
        """Rend ce qui est arrivé : `APPLIED`, `REFUSED`, `IGNORED` ou `REJECTED:<motif>`."""
        try:
            document = json.loads(raw.decode("utf-8"), parse_constant=_refuse_constant)
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            payload = raw.decode("utf-8", errors="replace")[:MAX_TEXT]
            return self._reject(
                "UNREADABLE", f"message illisible ({type(error).__name__})", payload, key
            )
        if isinstance(document, dict) and document.get("type") != RECOMMENDATION_TYPE:
            shown = str(document.get("type"))[:100]
            return self._reject(
                "UNKNOWN_TYPE",
                f"type {shown!r} non attendu sur {TOPIC_RECOMMENDATIONS}",
                document,
                key,
            )
        try:
            event = RecommendationEvent.model_validate(document)
        except ValidationError as error:
            return self._reject("CONTRACT_VIOLATION", contract_reason(error), document, key)
        if not self._service.knows(event.data.intersection_id):
            return self._reject(
                "SEMANTIC_VIOLATION",
                f"carrefour {event.data.intersection_id} sans feux dans ce service",
                document,
                key,
            )
        try:
            return self._service.on_recommendation(event)
        except Exception as error:  # un défaut du service ne bloque pas les messages suivants
            logger.exception("traitement d'une recommandation impossible")
            return self._reject(
                "PROCESSING_FAILED",
                f"traitement impossible ({type(error).__name__})",
                document,
                key,
            )

    # ------------------------------------------------------------------------------ rejet
    def _reject(self, code: str, reason: str, payload: Any, key: bytes | None) -> str:
        now = self._clock()
        subject = payload.get("subject") if isinstance(payload, dict) else None
        intersection = (
            subject if isinstance(subject, str) and INTERSECTION.fullmatch(subject) else None
        )
        event = _rejection(now, code, reason, payload, key, intersection)
        RejectedEvent.model_validate(event)  # le message d'erreur respecte lui aussi le contrat
        self._outbox.put(Outgoing(TOPIC_ERRORS, event["subject"], dumps(event), event["id"]))
        logger.info(
            "recommandation rejetée",
            extra={"fields": {"reason_code": code, "topic": TOPIC_ERRORS, "counter": "rejects"}},
        )
        return f"REJECTED:{code}"


def _rejection(
    now: datetime, code: str, reason: str, payload: Any, key: bytes | None, intersection: str | None
) -> dict[str, Any]:
    stamp = utc_stamp(now)
    return {
        "id": f"dlq:{SOURCE}:{TOPIC_RECOMMENDATIONS}:{int(now.timestamp() * 1000)}"
        f":{secrets.token_hex(4)}",
        "source": SOURCE,
        "type": "novaria.error.rejected.v1",
        "time": stamp,
        "subject": intersection or "UNKNOWN",
        "schema_version": "1.0",
        "domain": "error",
        "data": {
            "source_topic": TOPIC_RECOMMENDATIONS,
            "rejected_at": stamp,
            "reason_code": code,
            "reason": reason,
            "attempts": 1,
            "original_key": key.decode("utf-8", errors="replace")[:200] if key else None,
            "intersection_id": intersection,
            "original_payload": payload,
        },
    }
