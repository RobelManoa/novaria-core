"""Construction de `novaria.signal.status.v1` et des entrées d'audit (BE-05).

Chaque décision du contrôleur produit un événement, validé par le modèle commun avant de partir : un
défaut de construction est une erreur, jamais un message hors contrat sur le bus.
"""

import json
from datetime import datetime
from typing import Any

from app.domain.controller import StateView
from app.domain.model import Command, Decision, Origin, utc_stamp
from app.domain.safety import MIN_PHASE_S
from app.schemas.events import SignalStatusEvent

SOURCE = "reponse"
EVENT_TYPE = "novaria.signal.status.v1"
SERVICE_ACTOR = "reponse"  # l'acteur d'une décision que personne n'a demandée


def event_id(kind: str, decision: Decision, intersection_id: str, at: datetime) -> str:
    """Stable quand la décision a une référence (un rejeu redonne le même id), horodaté sinon."""
    if decision.reference_id:
        return f"{SOURCE}-{kind}-{decision.reference_id}"
    return f"{SOURCE}-{kind}-{intersection_id}-{int(at.timestamp() * 1000)}"


def status_event(
    view: StateView, decision: Decision, at: datetime, *, kind: str, correlation_id: str | None
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": event_id(kind, decision, view.intersection_id, at),
        "source": SOURCE,
        "type": EVENT_TYPE,
        "time": utc_stamp(at),
        "subject": view.intersection_id,
        "schema_version": "1.0",
        "domain": "signal",
        "data": {
            "intersection_id": view.intersection_id,
            "mode": view.mode.value,
            "current_phase_id": view.phase_id,
            "phase_started_at": utc_stamp(view.phase_started_at),
            "phases": [
                {
                    "phase_id": phase.phase_id,
                    "green_approaches": list(phase.green_approaches),
                    "min_duration_s": MIN_PHASE_S,
                    "duration_s": phase.duration_s,
                }
                for phase in view.phases
            ],
            "decision": {
                "origin": decision.origin.value,
                "reference_id": decision.reference_id,
                "outcome": decision.outcome.value,
                "refusal_reason": decision.refusal_reason,
            },
            "provenance": view.provenance.as_event(),
        },
    }
    if correlation_id:
        event["correlation_id"] = correlation_id
    SignalStatusEvent.model_validate(event)
    return event


def dumps(event: dict[str, Any]) -> bytes:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _entry(
    at: datetime, actor: str, action: str, refused: bool, correlation_id: str | None, details: dict
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "ts": at,
        "service": SOURCE,
        "actor": actor,
        "action": action,
        "outcome": "denied" if refused else "ok",
        "details": details,
    }
    if correlation_id:
        entry["correlation_id"] = correlation_id
    return entry


def command_entry(
    command: Command,
    decision: Decision,
    view: StateView,
    at: datetime,
    *,
    role: str,
    correlation_id: str | None,
) -> dict[str, Any]:
    """Une commande manuelle, acceptée ou refusée : qui, quoi, pourquoi, avec quel résultat."""
    return _entry(
        at,
        command.actor,
        f"signal.command.{command.action.value}",
        decision.refused,
        correlation_id,
        {
            "intersection_id": view.intersection_id,
            "command_id": command.command_id,
            "phase_id": command.phase_id,
            "duration_s": command.duration_s,
            "reason": command.reason,
            "role": role,
            "mode": view.mode.value,
            "refusal_reason": decision.refusal_reason,
            "refusal_detail": decision.detail if decision.refused else None,
        },
    )


_ACTIONS = {
    Origin.RECOMMENDATION: "signal.recommendation",
    Origin.FIXED_PLAN_FALLBACK: "signal.fixed_plan_fallback",
    Origin.STARTUP: "signal.startup",
    Origin.MANUAL_COMMAND: "signal.manual_command_ended",
}


def decision_entry(
    view: StateView, decision: Decision, at: datetime, *, event_id_: str, correlation_id: str | None
) -> dict[str, Any]:
    """Une décision que le service a prise seul : recommandation, retour au plan fixe, démarrage."""
    return _entry(
        at,
        SERVICE_ACTOR,
        _ACTIONS[decision.origin],
        decision.refused,
        correlation_id,
        {
            "intersection_id": view.intersection_id,
            "reference_id": decision.reference_id,
            "mode": view.mode.value,
            "refusal_reason": decision.refusal_reason,
            "refusal_detail": decision.detail if decision.refused else None,
            "event_id": event_id_,
        },
    )
