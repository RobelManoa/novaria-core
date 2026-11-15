"""Prévisions de vitesse à court terme : `/api/v1/forecasts` (IA-06).

Lecture seule, rôle `viewer` au moins. Pour l'instant la réponse est la référence par persistance
(`app/services/forecasts.py`) : aucun modèle entraîné n'existe encore, et la réponse le dit
(`model.kind` égal à `REFERENCE`). Paramètres et bornes :
`contracts/openapi/traitement.openapi.yaml`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import StringConstraints

from app.api.deps import require_role
from app.api.responses import errors
from app.api.v1.indicators import SEGMENT_PATTERN
from app.core.errors import FORECAST_UNAVAILABLE, ProblemError
from app.db.session import get_indicator_repository
from app.models import Role, User
from app.repositories.indicators import IndicatorRepository
from app.schemas.forecasts import (
    ForecastListResponse,
    ForecastModelResponse,
    ForecastResponse,
    ModelKind,
)
from app.schemas.indicators import Provenance
from app.services.forecasts import (
    REFERENCE_NAME,
    REFERENCE_VERSION,
    ForecastService,
    ForecastUnavailable,
    ReferenceForecast,
)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])
VIEWER = {"x-required-role": Role.VIEWER.value}

SegmentId = Annotated[str, StringConstraints(pattern=SEGMENT_PATTERN)]
MAX_SEGMENTS = 50


def get_forecast_service(
    indicators: IndicatorRepository = Depends(get_indicator_repository),
) -> ForecastService:
    return ForecastService(indicators)


def to_response(forecast: ReferenceForecast) -> ForecastResponse:
    row = forecast.row
    return ForecastResponse(
        road_segment_id=row.road_segment_id,
        issued_at=forecast.issued_at,
        horizon_min=forecast.horizon_min,
        target_time=forecast.target_time,
        predicted_speed_ratio=forecast.predicted_speed_ratio,
        predicted_state=row.congestion_state,
        model=ForecastModelResponse(
            kind=ModelKind.REFERENCE, name=REFERENCE_NAME, version=REFERENCE_VERSION, run_id=None
        ),
        provenance=Provenance(
            source_type=row.source_type,
            run_id=row.run_id,
            scenario_id=row.scenario_id,
            seed=row.seed,
            dataset_id=row.dataset_id,
        ),
    )


@router.get(
    "",
    response_model=ForecastListResponse,
    openapi_extra=VIEWER,
    responses=errors(401, 403, 422, 503, "5XX"),
)
def list_forecasts(
    road_segment_id: Annotated[list[SegmentId] | None, Query(max_length=MAX_SEGMENTS)] = None,
    horizon_min: int = Query(15, ge=5, le=60),
    _: User = Depends(require_role(Role.VIEWER)),
    service: ForecastService = Depends(get_forecast_service),
) -> ForecastListResponse:
    try:
        forecasts = service.persistence(horizon_min=horizon_min, road_segment_ids=road_segment_id)
    except ForecastUnavailable as error:
        raise ProblemError(
            FORECAST_UNAVAILABLE, "Aucune donnée dans l'entrepôt : ni modèle ni référence."
        ) from error
    return ForecastListResponse(items=[to_response(forecast) for forecast in forecasts])
