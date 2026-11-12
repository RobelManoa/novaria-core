"""Réponse de la route de prévisions (IA-06) : schéma `Forecast` de `traitement.openapi.yaml`.

Mêmes champs et mêmes bornes que le contrat. `model.kind` vaut `REFERENCE` tant qu'aucun modèle
entraîné n'a battu la référence (ADR-015) ; `run_id` du modèle vaut alors `null`.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_serializer

from app.schemas.indicators import CongestionState, Provenance


class ModelKind(StrEnum):
    REFERENCE = "REFERENCE"
    MODEL = "MODEL"


class ForecastModelResponse(BaseModel):
    kind: ModelKind
    name: str
    version: str
    run_id: str | None = Field(
        description="Identifiant du run d'entraînement ; null pour une référence."
    )


class ForecastResponse(BaseModel):
    road_segment_id: str
    issued_at: datetime
    horizon_min: int = Field(ge=5, le=60)
    target_time: datetime
    predicted_speed_ratio: float = Field(ge=0, le=9.999)
    predicted_state: CongestionState
    model: ForecastModelResponse
    provenance: Provenance

    @field_serializer("issued_at", "target_time")
    def in_utc(self, value: datetime) -> datetime:
        """Le contrat veut une date UTC (`...Z`), quel que soit le fuseau de la session de base."""
        return value.astimezone(UTC)


class ForecastListResponse(BaseModel):
    items: list[ForecastResponse]
