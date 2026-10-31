"""Indicateurs par fenêtre, lus depuis l'entrepôt (BE-04) : `/api/v1/indicators`.

Lecture seule. Chaque route exige au moins le rôle `viewer`. Les filtres et leurs bornes sont ceux
de `contracts/openapi/traitement.openapi.yaml`.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_role
from app.core.errors import NOT_FOUND, VALIDATION_ERROR, ProblemError
from app.db.session import get_indicator_repository
from app.models import Role, User
from app.repositories.indicators import IndicatorFilters, IndicatorRepository
from app.schemas.indicators import (
    CongestionState,
    IndicatorPageResponse,
    IndicatorResponse,
    LatestIndicatorsResponse,
    SourceType,
    WindowSize,
)
from app.services.indicators import DEFAULT_LIMIT, MAX_LIMIT, IndicatorService, InvalidCursor

router = APIRouter(prefix="/indicators", tags=["indicators"])
VIEWER = {"x-required-role": Role.VIEWER.value}

INTERSECTION_PATTERN = r"^INT_[0-9]{2,}$"
SEGMENT_PATTERN = r"^ROAD_[0-9]{3,}$"
UTC_DATETIME_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$"


def get_indicator_service(
    indicators: IndicatorRepository = Depends(get_indicator_repository),
) -> IndicatorService:
    return IndicatorService(indicators)


def parse_utc(value: str | None, field: str) -> datetime | None:
    """Lit une date `...Z` ; une date impossible (30 février, 25 h) donne une erreur de champ."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as error:
        raise ProblemError(
            VALIDATION_ERROR,
            "1 champ invalide.",
            errors=[{"field": f"query.{field}", "message": "Date et heure UTC impossibles."}],
        ) from error


@router.get("", response_model=IndicatorPageResponse, openapi_extra=VIEWER)
def list_indicators(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None, max_length=512),
    intersection_id: str | None = Query(None, pattern=INTERSECTION_PATTERN),
    road_segment_id: str | None = Query(None, pattern=SEGMENT_PATTERN),
    from_: str | None = Query(None, alias="from", pattern=UTC_DATETIME_PATTERN),
    to: str | None = Query(None, pattern=UTC_DATETIME_PATTERN),
    window_size_s: WindowSize = WindowSize.ONE_MINUTE,
    congestion_state: CongestionState | None = None,
    run_id: str | None = Query(None, min_length=1, max_length=80),
    source_type: SourceType | None = None,
    _: User = Depends(require_role(Role.VIEWER)),
    service: IndicatorService = Depends(get_indicator_service),
) -> IndicatorPageResponse:
    start, end = parse_utc(from_, "from"), parse_utc(to, "to")
    if start is not None and end is not None and end <= start:
        raise ProblemError(
            VALIDATION_ERROR,
            "1 champ invalide.",
            errors=[{"field": "query.to", "message": "Doit être postérieure à `from`."}],
        )
    filters = IndicatorFilters(
        window_size_s=window_size_s.value,
        intersection_id=intersection_id,
        road_segment_id=road_segment_id,
        start=start,
        end=end,
        congestion_state=congestion_state.value if congestion_state else None,
        run_id=run_id,
        source_type=source_type.value if source_type else None,
    )
    try:
        page = service.list_page(filters, limit=limit, cursor=cursor)
    except InvalidCursor as error:
        raise ProblemError(
            VALIDATION_ERROR,
            "1 champ invalide.",
            errors=[{"field": "query.cursor", "message": "Curseur inconnu."}],
        ) from error
    return IndicatorPageResponse(
        items=[IndicatorResponse.from_row(row) for row in page.items],
        next_cursor=page.next_cursor,
    )


# Avant `/{indicator_id}` : « latest » ne doit pas être pris pour un identifiant.
@router.get("/latest", response_model=LatestIndicatorsResponse, openapi_extra=VIEWER)
def latest_indicators(
    intersection_id: str | None = Query(None, pattern=INTERSECTION_PATTERN),
    run_id: str | None = Query(None, min_length=1, max_length=80),
    _: User = Depends(require_role(Role.VIEWER)),
    service: IndicatorService = Depends(get_indicator_service),
) -> LatestIndicatorsResponse:
    rows = service.latest(intersection_id=intersection_id, run_id=run_id)
    return LatestIndicatorsResponse(items=[IndicatorResponse.from_row(row) for row in rows])


@router.get("/{indicator_id}", response_model=IndicatorResponse, openapi_extra=VIEWER)
def get_indicator(
    indicator_id: str,
    _: User = Depends(require_role(Role.VIEWER)),
    service: IndicatorService = Depends(get_indicator_service),
) -> IndicatorResponse:
    row = service.get(indicator_id)
    if row is None:
        raise ProblemError(NOT_FOUND, "Indicateur inconnu.")
    return IndicatorResponse.from_row(row)
