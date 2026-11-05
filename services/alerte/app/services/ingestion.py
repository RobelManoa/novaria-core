"""Un message de `traffic.indicators` : valider, évaluer les règles, ouvrir ou résoudre (MS-11).

Un message hors contrat n'arrête rien : il part sur `errors.dlq` avec son motif (le service d'alerte
n'a pas de MongoDB, il n'archive pas de copie : le sujet fait foi). Une panne de la base ou du bus,
elle, est remontée (`StoreFailed`, `PublishFailed`) : la boucle s'arrête sans valider l'offset et le
message est relu au redémarrage (livraison au moins une fois ; rejouer un indicateur est sans
effet).
"""

import json
import logging
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.core.config import TOPIC_ERRORS, TOPIC_INDICATORS
from app.domain.model import Provenance, Resolve, Rule, Window, parse_utc, utc_stamp
from app.domain.rules import RuleEngine
from app.schemas.events import IndicatorEvent, RejectedEvent
from app.services.alerts import AlertService, Clock, OpenOutcome, utcnow
from app.services.events import dumps
from app.services.ports import EventPublisher

logger = logging.getLogger("app.ingestion")

SERVICE = "alerte"
INDICATOR_TYPE = "novaria.traffic.indicator.v1"
MAX_TEXT = 20000  # un message illisible est conservé sous forme de texte, tronqué
INTERSECTION = re.compile(r"INT_[0-9]{2,}")


def _refuse_constant(name: str) -> None:
    raise ValueError(f"constante JSON non permise : {name}")  # NaN, Infinity : pas du JSON strict


@dataclass
class Handled:
    """Ce qu'un message a produit."""

    rejected: str | None = None  # code du motif, si le message a été rejeté
    outcomes: list[str] = field(default_factory=list)


def to_window(event: IndicatorEvent) -> Window:
    data = event.data
    provenance = data.provenance
    return Window(
        event_id=event.id,
        event_time=parse_utc(event.time),
        correlation_id=event.correlation_id,
        intersection_id=data.intersection_id,
        road_segment_id=data.road_segment_id,
        window_start=parse_utc(data.window_start),
        window_size_s=data.window_size_s,
        congestion_state=data.congestion_state,
        sample_count=data.sample_count,
        speed_ratio=data.speed_ratio,
        occupancy_rate=data.occupancy_rate,
        max_queue_length_m=data.max_queue_length_m,
        provenance=Provenance(
            provenance.source_type,
            provenance.run_id,
            provenance.scenario_id,
            provenance.seed,
            provenance.dataset_id,
        ),
    )


def contract_reason(error: ValidationError) -> str:
    """Le premier défaut, au chemin et au message de la bibliothèque, sans la valeur refusée."""
    first = error.errors(include_input=False)[0]
    path = "/".join(str(part) for part in first["loc"])
    more = len(error.errors()) - 1
    return f"{path} : {first['msg']}" + (f" (et {more} autre(s))" if more else "")


class IndicatorHandler:
    def __init__(
        self,
        service: AlertService,
        engine: RuleEngine,
        rules: Callable[[], list[Rule]],
        publisher: EventPublisher,
        *,
        clock: Clock = utcnow,
    ) -> None:
        self._service = service
        self._engine = engine
        self._rules = rules
        self._publisher = publisher
        self._clock = clock

    def handle(self, raw: bytes, key: bytes | None = None) -> Handled:
        try:
            text = raw.decode("utf-8")
            document = json.loads(text, parse_constant=_refuse_constant)
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            payload = raw.decode("utf-8", errors="replace")[:MAX_TEXT]
            return self._reject(
                "UNREADABLE", f"message illisible ({type(error).__name__})", payload, key
            )
        if isinstance(document, dict) and document.get("type") != INDICATOR_TYPE:
            reason = f"type {str(document.get('type'))[:100]!r} non attendu sur {TOPIC_INDICATORS}"
            return self._reject("UNKNOWN_TYPE", reason, document, key)
        try:
            event = IndicatorEvent.model_validate(document)
        except ValidationError as error:
            return self._reject("CONTRACT_VIOLATION", contract_reason(error), document, key)
        return self._evaluate(to_window(event))

    def _evaluate(self, window: Window) -> Handled:
        handled = Handled()
        try:
            for decision in self._engine.evaluate(window, self._rules()):
                if isinstance(decision, Resolve):
                    if self._service.resolve_auto(decision) is not None:
                        handled.outcomes.append("RESOLVED")
                elif self._service.open(decision) is OpenOutcome.CREATED:
                    handled.outcomes.append("CREATED")
        except Exception:
            self._engine.revert()  # la fenêtre n'a pas été traitée : son rejeu doit l'être
            raise
        return handled

    # ------------------------------------------------------------------------------ rejet
    def _reject(self, code: str, reason: str, payload: Any, key: bytes | None) -> Handled:
        now = self._clock()
        intersection = _intersection_of(payload)
        event = _rejection(now, code, reason, payload, key, intersection)
        RejectedEvent.model_validate(event)  # le message d'erreur respecte lui aussi le contrat
        self._publisher.publish(TOPIC_ERRORS, event["subject"], dumps(event))
        self._publisher.flush()
        logger.info(
            "indicateur rejeté",
            extra={"fields": {"reason_code": code, "topic": TOPIC_ERRORS, "counter": "rejects"}},
        )
        return Handled(rejected=code)


def _intersection_of(payload: Any) -> str | None:
    subject = payload.get("subject") if isinstance(payload, dict) else None
    return subject if isinstance(subject, str) and INTERSECTION.fullmatch(subject) else None


def _rejection(
    now: datetime, code: str, reason: str, payload: Any, key: bytes | None, intersection: str | None
) -> dict[str, Any]:
    stamp = utc_stamp(now)
    return {
        "id": f"dlq:{SERVICE}:{TOPIC_INDICATORS}:{int(now.timestamp() * 1000)}"
        f":{secrets.token_hex(4)}",
        "source": SERVICE,
        "type": "novaria.error.rejected.v1",
        "time": stamp,
        "subject": intersection or "UNKNOWN",
        "schema_version": "1.0",
        "correlation_id": f"corr-{int(now.timestamp() * 1000)}",
        "domain": "error",
        "data": {
            "source_topic": TOPIC_INDICATORS,
            "rejected_at": stamp,
            "reason_code": code,
            "reason": reason,
            "attempts": 1,
            "original_key": key.decode("utf-8", errors="replace")[:200] if key else None,
            "intersection_id": intersection,
            "original_payload": payload,
        },
    }
