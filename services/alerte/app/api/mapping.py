"""Du modèle du service aux corps de l'API : dates au format du contrat, curseur de pagination."""

import base64
import json
import uuid
from datetime import datetime

from app.domain.model import Alert, HistoryEntry, Rule, parse_utc, utc_stamp


def alert_out(alert: Alert) -> dict:
    def stamp(moment: datetime | None) -> str | None:
        return utc_stamp(moment) if moment else None

    return {
        "alert_id": alert.alert_id,
        "rule_id": alert.rule_id,
        "kind": alert.kind.value,
        "state": alert.state.value,
        "severity": alert.severity.value,
        "cause": alert.cause,
        "road_segment_id": alert.road_segment_id,
        "intersection_id": alert.intersection_id,
        "episode_id": alert.episode_id,
        "opened_at": utc_stamp(alert.opened_at),
        "notified_at": stamp(alert.notified_at),
        "acknowledged_at": stamp(alert.acknowledged_at),
        "acknowledged_by": alert.acknowledged_by,
        "resolved_at": stamp(alert.resolved_at),
        "resolution": alert.resolution,
        "provenance": alert.provenance.as_event(),
    }


def history_out(entry: HistoryEntry) -> dict:
    comment = (entry.details or {}).get("comment")
    return {
        "from_state": entry.from_state.value if entry.from_state else None,
        "to_state": entry.to_state.value,
        "changed_at": utc_stamp(entry.changed_at),
        "actor": entry.actor,
        "comment": comment if isinstance(comment, str) else None,
    }


def rule_out(rule: Rule) -> dict:
    return {
        "rule_id": rule.rule_id,
        "kind": rule.kind.value,
        "enabled": rule.enabled,
        "params": rule.params,
        "min_gap_s": rule.min_gap_s,
        "updated_at": utc_stamp(rule.updated_at) if rule.updated_at else None,
    }


def encode_cursor(alert: Alert) -> str:
    """Curseur opaque : (ouverture, identifiant) de la dernière alerte de la page."""
    raw = json.dumps([utc_stamp(alert.opened_at), alert.alert_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Lève `ValueError` pour tout curseur qui n'a pas été produit par `encode_cursor`."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        opened_at, alert_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(opened_at, str) or not isinstance(alert_id, str):
            raise TypeError
        return parse_utc(opened_at), str(uuid.UUID(alert_id))
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError("curseur invalide") from error
