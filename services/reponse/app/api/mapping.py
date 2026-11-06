"""Du modèle du service aux corps de l'API : dates au format du contrat."""

from typing import Any

from app.domain.controller import StateView
from app.domain.model import Command, Decision, utc_stamp
from app.domain.safety import MIN_PHASE_S


def state_out(view: StateView) -> dict[str, Any]:
    decision = view.decision
    return {
        "intersection_id": view.intersection_id,
        "mode": view.mode.value,
        "current_phase_id": view.phase_id,
        "phase_started_at": utc_stamp(view.phase_started_at),
        "phase_ends_at": utc_stamp(view.phase_ends_at),
        "signal": view.signal,
        "green_approaches": list(view.green_approaches),
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
        "updated_at": utc_stamp(view.updated_at),
        "provenance": view.provenance.as_event(),
    }


def command_out(
    command: Command, decision: Decision, intersection_id: str, requested_at_text: str
) -> dict[str, Any]:
    return {
        "command_id": command.command_id,
        "intersection_id": intersection_id,
        "action": command.action.value,
        "phase_id": command.phase_id,
        "duration_s": command.duration_s,
        "status": "REFUSED" if decision.refused else "APPLIED",
        "refusal_reason": decision.refusal_reason,
        "requested_by": command.actor,
        "requested_at": requested_at_text,
        "reason": command.reason,
    }


def history_out(entry: dict[str, Any]) -> dict[str, Any]:
    """Une entrée `audit_logs` de commande, relue comme `SignalCommand`."""
    details = entry.get("details") or {}
    return {
        "command_id": details.get("command_id", ""),
        "intersection_id": details.get("intersection_id", ""),
        "action": str(entry["action"]).rsplit(".", 1)[-1],
        "phase_id": details.get("phase_id"),
        "duration_s": details.get("duration_s"),
        "status": "REFUSED" if entry.get("outcome") == "denied" else "APPLIED",
        "refusal_reason": details.get("refusal_reason"),
        "requested_by": entry["actor"],
        "requested_at": utc_stamp(entry["ts"]),
        "reason": details.get("reason", ""),
    }
