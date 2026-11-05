"""Corps d'erreur de l'API : schéma `Problem` de `contracts/openapi/common.yaml` (BE-06).

Ce modèle ne sert qu'à décrire les erreurs dans la documentation générée (`/docs`,
`/openapi.json`) : les corps réels sont construits par `ProblemError.body()`
(`app/core/errors.py`). Un test compare les codes de ce modèle à ceux du contrat.
"""

from typing import Literal

from pydantic import BaseModel, Field

ProblemCode = Literal[
    "UNAUTHENTICATED",
    "INVALID_CREDENTIALS",
    "FORBIDDEN",
    "NOT_FOUND",
    "METHOD_NOT_ALLOWED",
    "CONFLICT",
    "VALIDATION_ERROR",
    "INVALID_STATE_TRANSITION",
    "COMMAND_IN_PROGRESS",
    "UNSAFE_COMMAND",
    "RATE_LIMITED",
    "FORECAST_UNAVAILABLE",
    "UPSTREAM_UNAVAILABLE",
    "INTERNAL_ERROR",
]


class FieldError(BaseModel):
    field: str = Field(description="Chemin du champ, par exemple `body.password` ou `query.limit`.")
    message: str


class Problem(BaseModel):
    """Corps unique de toute erreur (RFC 9457, `application/problem+json`)."""

    type: str = Field(description="Identifie la famille d'erreur.")
    title: str = Field(description="Résumé court, identique pour un même `code`.")
    status: int = Field(ge=400, le=599, description="Code HTTP, répété dans le corps.")
    code: ProblemCode = Field(description="Code stable lisible par une machine.")
    detail: str | None = Field(
        default=None, description="Explication pour une personne, sans secret ni trace."
    )
    correlation_id: str = Field(description="Identifiant de corrélation de la requête.")
    errors: list[FieldError] | None = Field(
        default=None, description="Un élément par champ invalide (`VALIDATION_ERROR`)."
    )
