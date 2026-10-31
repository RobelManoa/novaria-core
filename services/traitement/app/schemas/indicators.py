"""Réponses des routes d'indicateurs (BE-04).

Mêmes champs, mêmes unités et mêmes bornes que les schémas `Indicator`, `IndicatorPage` et
`Provenance` de `contracts/openapi/traitement.openapi.yaml` et de `common.yaml`.
"""

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_serializer

from app.repositories.indicators import IndicatorRow


class CongestionState(StrEnum):
    UNKNOWN = "UNKNOWN"
    FREE_FLOW = "FREE_FLOW"
    SLOW = "SLOW"
    CONGESTED = "CONGESTED"


class SourceType(StrEnum):
    SIMULATED = "SIMULATED"
    REAL_HISTORICAL = "REAL_HISTORICAL"
    REAL_LIVE = "REAL_LIVE"


class WindowSize(IntEnum):
    """Taille de fenêtre en secondes. Un paramètre de requête arrive en texte : d'où l'IntEnum."""

    ONE_MINUTE = 60
    FIVE_MINUTES = 300


class Provenance(BaseModel):
    """Origine de la donnée ; seuls les champs renseignés figurent dans la réponse."""

    source_type: SourceType
    run_id: str
    scenario_id: str | None = None
    seed: int | None = None
    dataset_id: str | None = None

    @model_serializer(mode="wrap")
    def without_empty_fields(self, handler) -> dict[str, Any]:
        return {key: value for key, value in handler(self).items() if value is not None}


class IndicatorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    indicator_id: str
    road_segment_id: str
    intersection_id: str
    window_start: datetime
    window_size_s: Literal[60, 300]
    vehicle_count: int
    flow_veh_per_min: float
    average_speed_kmh: float | None
    occupancy_rate: float | None
    max_queue_length_m: float | None
    speed_ratio: float | None
    sample_count: int
    expected_sample_count: int
    completeness: float
    congestion_state: CongestionState
    classifier_version: str
    provenance: Provenance

    @field_serializer("window_start")
    def window_start_in_utc(self, value: datetime) -> datetime:
        """Le contrat veut une date UTC (`...Z`), quel que soit le fuseau de la session de base."""
        return value.astimezone(UTC)

    @classmethod
    def from_row(cls, row: IndicatorRow) -> "IndicatorResponse":
        return cls(
            indicator_id=row.indicator_id,
            road_segment_id=row.road_segment_id,
            intersection_id=row.intersection_id,
            window_start=row.window_start,
            window_size_s=row.window_size_s,
            vehicle_count=row.vehicle_count,
            flow_veh_per_min=row.flow_veh_per_min,
            average_speed_kmh=row.average_speed_kmh,
            occupancy_rate=row.occupancy_rate,
            max_queue_length_m=row.max_queue_length_m,
            speed_ratio=row.speed_ratio,
            sample_count=row.sample_count,
            expected_sample_count=row.expected_sample_count,
            completeness=row.completeness,
            congestion_state=row.congestion_state,
            classifier_version=row.classifier_version,
            provenance=Provenance(
                source_type=row.source_type,
                run_id=row.run_id,
                scenario_id=row.scenario_id,
                seed=row.seed,
                dataset_id=row.dataset_id,
            ),
        )


class IndicatorPageResponse(BaseModel):
    items: list[IndicatorResponse]
    next_cursor: str | None = Field(
        description="Curseur de la page suivante ; null sur la dernière."
    )


class LatestIndicatorsResponse(BaseModel):
    items: list[IndicatorResponse]
