"""Construction de l'événement `novaria.alert.state_changed.v1` (contrat `alert-event.schema.json`).

Chaque changement d'état en produit un, validé par le modèle commun avant d'être écrit dans la boîte
d'envoi : un défaut de construction est une erreur, jamais un message hors contrat sur le bus.
"""

import json
from datetime import datetime
from typing import Any

from app.domain.model import Alert, State, utc_stamp
from app.schemas.events import AlertEvent

SOURCE = "alerte"
EVENT_TYPE = "novaria.alert.state_changed.v1"


def event_id(alert_id: str, state: State) -> str:
    """Un événement par état atteint, et un état n'est jamais rejoué : l'identifiant est stable."""
    return f"alerte-{alert_id}-{state.value.lower()}"


def build_event(alert: Alert, previous: State | None, at: datetime) -> dict[str, Any]:
    """L'événement de l'alerte telle qu'elle est maintenant, `at` étant le moment du changement."""
    event = {
        "id": event_id(alert.alert_id, alert.state),
        "source": SOURCE,
        "type": EVENT_TYPE,
        "time": utc_stamp(at),
        "subject": alert.intersection_id,
        "schema_version": "1.0",
        "domain": "alert",
        "data": {
            "alert_id": alert.alert_id,
            "rule_id": alert.rule_id,
            "kind": alert.kind.value,
            "state": alert.state.value,
            "previous_state": previous.value if previous else None,
            "severity": alert.severity.value,
            "cause": alert.cause,
            "road_segment_id": alert.road_segment_id,
            "intersection_id": alert.intersection_id,
            "episode_id": alert.episode_id,
            "opened_at": utc_stamp(alert.opened_at),
            "resolved_at": utc_stamp(alert.resolved_at) if alert.resolved_at else None,
            "resolution": alert.resolution,
            "provenance": alert.provenance.as_event(),
        },
    }
    if alert.correlation_id:
        event["correlation_id"] = alert.correlation_id
    AlertEvent.model_validate(event)
    return event


def dumps(event: dict[str, Any]) -> bytes:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
