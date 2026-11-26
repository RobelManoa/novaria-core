"""Réponses des routes des réseaux de vitesse (IA-16) : schémas de `traitement.openapi.yaml`."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_serializer

from app.schemas.forecasts import ModelKind


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


class PeriodResponse(BaseModel):
    start: datetime
    end: datetime
    steps: int


class HorizonScoreResponse(BaseModel):
    """Erreur du modèle sur la période de test, en miles par heure (l'unité de la source), contre la
    persistance."""

    mae_model_mph: float
    mae_persistence_mph: float
    gain: float = Field(description="1 − erreur du modèle / erreur de la persistance.")
    interval_95: list[float] = Field(min_length=2, max_length=2)
    mae_hgb_mph: float | None = None


class ModelCardResponse(BaseModel):
    kind: ModelKind
    name: str
    version: str
    run_id: str | None
    trained_at: datetime | None
    dataset: str
    source_type: str
    parameters: int
    horizons_min: list[int]
    periods: dict[str, PeriodResponse]
    test: dict[str, HorizonScoreResponse]
    variables: list[str]
    limits: list[str]
    file_sha256: str

    @field_serializer("trained_at")
    def in_utc(self, value: datetime | None) -> datetime | None:
        return _utc(value)


class CoverageResponse(BaseModel):
    first: datetime | None
    last: datetime | None
    steps: int
    sensors: int

    @field_serializer("first", "last")
    def in_utc(self, value: datetime | None) -> datetime | None:
        return _utc(value)


class SpeedNetworkResponse(BaseModel):
    network_id: str
    label: str
    description: str
    source_type: str
    step_s: int
    speed_unit: str
    coverage: CoverageResponse
    model: ModelCardResponse | None
    model_problem: str | None = Field(
        description="Pourquoi il n'y a pas de modèle utilisable, quand `model` est null."
    )


class SpeedNetworkListResponse(BaseModel):
    items: list[SpeedNetworkResponse]


class SensorForecastResponse(BaseModel):
    sensor_id: str
    target_time: datetime
    predicted_speed_kmh: float
    persistence_speed_kmh: float
    observed_speed_kmh: float | None = Field(
        description="Vitesse réellement mesurée à `target_time`, si elle est déjà dans l'entrepôt."
    )

    @field_serializer("target_time")
    def in_utc(self, value: datetime) -> datetime:
        return value.astimezone(UTC)


class SpeedForecastListResponse(BaseModel):
    network_id: str
    as_of: datetime
    horizon_min: int
    model: ModelCardResponse
    sensors_without_model: int
    items: list[SensorForecastResponse]

    @field_serializer("as_of")
    def in_utc(self, value: datetime) -> datetime:
        return value.astimezone(UTC)
