"""Modèle du contrôleur de feux : modes, décisions, commandes (MS-12). Domaine pur."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class Mode(StrEnum):
    AUTOMATIC = "AUTOMATIC"  # suit les recommandations
    MANUAL = "MANUAL"  # un opérateur tient une phase
    DEGRADED_FIXED_PLAN = "DEGRADED_FIXED_PLAN"  # plan à durées fixes : pas de recommandation


class Origin(StrEnum):
    RECOMMENDATION = "RECOMMENDATION"
    MANUAL_COMMAND = "MANUAL_COMMAND"
    FIXED_PLAN_FALLBACK = "FIXED_PLAN_FALLBACK"
    STARTUP = "STARTUP"


class Outcome(StrEnum):
    APPLIED = "APPLIED"
    REFUSED = "REFUSED"


class Action(StrEnum):
    SET_PHASE = "SET_PHASE"
    RESUME_AUTOMATIC = "RESUME_AUTOMATIC"


@dataclass(frozen=True)
class Provenance:
    source_type: str
    run_id: str
    scenario_id: str | None = None
    seed: int | None = None
    dataset_id: str | None = None

    def as_event(self) -> dict:
        fields = {
            "source_type": self.source_type,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "dataset_id": self.dataset_id,
        }
        return {name: value for name, value in fields.items() if value is not None}


@dataclass(frozen=True)
class Command:
    """Une commande manuelle, telle que l'API l'a reçue."""

    command_id: str
    action: Action
    actor: str  # identifiant du compte (`sub` du jeton), jamais un nom
    reason: str
    phase_id: str | None = None
    duration_s: int | None = None


@dataclass(frozen=True)
class Decision:
    """Ce que le contrôleur a décidé : appliqué, ou refusé avec son motif (`signal.status`)."""

    origin: Origin
    reference_id: str | None
    outcome: Outcome
    refusal_reason: str | None = None
    detail: str | None = None  # pour l'humain (journal d'audit, réponse 422) ; jamais sur le bus
    reasons: tuple[str, ...] = ()  # tous les codes violés, le premier est `refusal_reason`
    changed: bool = True  # faux : refus, ou commande sans effet ; l'état n'a pas bougé

    @property
    def refused(self) -> bool:
        return self.outcome is Outcome.REFUSED


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc_stamp(moment: datetime) -> str:
    """Instant UTC en secondes, au format du contrat (`…Z`)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
