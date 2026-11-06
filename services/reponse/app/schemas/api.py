"""Corps des réponses et des requêtes de l'API de réponse (schémas de `reponse.openapi.yaml`).

Les dates sont des chaînes UTC au format du contrat (`2026-10-20T08:21:00Z`) : elles sont écrites
par `app/api/mapping.py`, pas par Pydantic, qui ne produit pas le `Z`.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SignalPhaseOut(BaseModel):
    phase_id: str
    green_approaches: list[Literal["N", "E", "S", "W"]]
    min_duration_s: int
    duration_s: int


class SignalDecisionOut(BaseModel):
    origin: Literal["RECOMMENDATION", "MANUAL_COMMAND", "FIXED_PLAN_FALLBACK", "STARTUP"]
    reference_id: str | None
    outcome: Literal["APPLIED", "REFUSED"]
    refusal_reason: str | None


class SignalStateOut(BaseModel):
    """`SignalState` du contrat : l'état du contrôleur, avec la décision qui l'a produit."""

    intersection_id: str
    mode: Literal["AUTOMATIC", "MANUAL", "DEGRADED_FIXED_PLAN"]
    current_phase_id: str
    phase_started_at: str
    phase_ends_at: str
    signal: Literal["GREEN", "ALL_RED"]
    green_approaches: list[Literal["N", "E", "S", "W"]]
    phases: list[SignalPhaseOut]
    decision: SignalDecisionOut
    updated_at: str
    provenance: dict[str, Any]


class SignalStateListOut(BaseModel):
    items: list[SignalStateOut]


class SignalCommandIn(BaseModel):
    """`SignalCommandRequest` du contrat : refuse tout champ inconnu."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["SET_PHASE", "RESUME_AUTOMATIC"]
    phase_id: Annotated[str | None, Field(pattern=r"^P[0-9]+$")] = None
    duration_s: Annotated[int | None, Field(ge=1, le=600)] = None
    reason: Annotated[str, Field(min_length=3, max_length=500)]

    @field_validator("reason")
    @classmethod
    def reason_is_text(cls, value: str) -> str:
        """Un motif est une phrase : espaces superflus retirés, pas de caractère de commande."""
        value = value.strip()
        if len(value) < 3 or any(ord(char) < 32 and char not in "\t" for char in value):
            raise ValueError("le motif est un texte de 3 à 500 caractères, sans saut de ligne")
        return value

    @model_validator(mode="after")
    def set_phase_needs_phase_and_duration(self) -> "SignalCommandIn":
        if self.action == "SET_PHASE" and (self.phase_id is None or self.duration_s is None):
            raise ValueError("phase_id et duration_s sont obligatoires avec SET_PHASE")
        return self


class SignalCommandOut(BaseModel):
    """`SignalCommand` du contrat. `status` : APPLIED ou REFUSED (les autres : réservés)."""

    command_id: str
    intersection_id: str
    action: Literal["SET_PHASE", "RESUME_AUTOMATIC"]
    phase_id: str | None
    duration_s: int | None
    status: Literal["ACCEPTED", "APPLIED", "REFUSED", "EXPIRED"]
    refusal_reason: str | None
    requested_by: str
    requested_at: str
    reason: str


class SignalCommandPageOut(BaseModel):
    items: list[SignalCommandOut]
    next_cursor: str | None


class Problem(BaseModel):
    """Corps d'erreur (`Problem`, RFC 9457) : seulement pour décrire les réponses d'erreur."""

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    correlation_id: str
    errors: list[dict[str, str]] | None = None
