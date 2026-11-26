"""Réseaux de vitesse et prévisions d'un modèle entraîné : `/api/v1/speed-networks` (IA-16,
ADR-032).

Lecture seule, rôle `viewer` au moins. La réponse dit toujours quel modèle a parlé (`model`, avec sa
fiche : jeu, périodes, erreurs de test
contre la persistance, limites) et d'où viennent les données (`source_type`). Contrat :
`contracts/openapi/traitement.openapi.yaml`.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import StringConstraints

from app.api.deps import require_role
from app.api.responses import errors
from app.core.config import get_settings
from app.core.errors import FORECAST_UNAVAILABLE, NOT_FOUND, VALIDATION_ERROR, ProblemError
from app.db.session import get_speed_repository
from app.models import Role, User
from app.repositories.speed import SpeedRepository
from app.schemas.forecasts import ModelKind
from app.schemas.speed_forecasts import (
    CoverageResponse,
    HorizonScoreResponse,
    ModelCardResponse,
    PeriodResponse,
    SensorForecastResponse,
    SpeedForecastListResponse,
    SpeedNetworkListResponse,
    SpeedNetworkResponse,
)
from app.services.speed_forecasts import (
    HORIZONS_MIN,
    LoadedModel,
    ModelUnavailable,
    NetworkNotFound,
    NoDataBefore,
    SpeedForecastService,
)

router = APIRouter(prefix="/speed-networks", tags=["speed-networks"])
VIEWER = {"x-required-role": Role.VIEWER.value}

NetworkId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
SensorId = Annotated[str, StringConstraints(min_length=1, max_length=40)]
MAX_SENSORS = 50


def get_speed_service(
    repository: SpeedRepository = Depends(get_speed_repository),
) -> SpeedForecastService:
    directory = get_settings().models_dir
    return SpeedForecastService(repository, Path(directory) if directory else None)


def to_card(loaded: LoadedModel) -> ModelCardResponse:
    meta = loaded.model.meta
    return ModelCardResponse(
        kind=ModelKind.MODEL,
        name=str(meta.get("nom", "modele")),
        version=str(meta.get("version", "1")),
        run_id=None,
        trained_at=meta.get("entraine_le"),
        dataset=str(meta.get("jeu", "")),
        source_type=str(meta.get("type_de_source", "")),
        parameters=int(meta.get("poids", 0)),
        horizons_min=list(meta.get("horizons_min", [])),
        periods={
            name: PeriodResponse(start=p["debut"], end=p["fin"], steps=p["pas"])
            for name, p in meta.get("periodes", {}).items()
        },
        test={
            minutes: HorizonScoreResponse(
                mae_model_mph=t["mae_modele"],
                mae_persistence_mph=t["mae_persistance"],
                gain=t["gain"],
                interval_95=list(t["intervalle_95"]),
                mae_hgb_mph=t.get("mae_hgb_ia16"),
            )
            for minutes, t in meta.get("test", {}).items()
        },
        variables=list(meta.get("variables", [])),
        limits=list(meta.get("limites", [])),
        file_sha256=loaded.file_sha256,
    )


@router.get(
    "",
    response_model=SpeedNetworkListResponse,
    openapi_extra=VIEWER,
    responses=errors(401, 403, "5XX"),
)
def list_speed_networks(
    _: User = Depends(require_role(Role.VIEWER)),
    service: SpeedForecastService = Depends(get_speed_service),
) -> SpeedNetworkListResponse:
    return SpeedNetworkListResponse(
        items=[
            SpeedNetworkResponse(
                network_id=s.network.network_id,
                label=s.network.label,
                description=s.network.description,
                source_type=s.network.source_type,
                step_s=s.network.step_s,
                speed_unit=s.network.speed_unit,
                coverage=CoverageResponse(
                    first=s.coverage.first,
                    last=s.coverage.last,
                    steps=s.coverage.steps,
                    sensors=s.coverage.sensors,
                ),
                model=to_card(s.model) if s.model else None,
                model_problem=s.model_problem,
            )
            for s in service.networks()
        ]
    )


@router.get(
    "/{network_id}/forecasts",
    response_model=SpeedForecastListResponse,
    openapi_extra=VIEWER,
    responses=errors(401, 403, 404, 422, 503, "5XX"),
)
def list_speed_forecasts(
    network_id: NetworkId,
    as_of: datetime | None = Query(None),
    horizon_min: int = Query(15, ge=5, le=30),
    sensor_id: Annotated[list[SensorId] | None, Query(max_length=MAX_SENSORS)] = None,
    _: User = Depends(require_role(Role.VIEWER)),
    service: SpeedForecastService = Depends(get_speed_service),
) -> SpeedForecastListResponse:
    if horizon_min not in HORIZONS_MIN:
        raise ProblemError(
            VALIDATION_ERROR, "horizon_min doit être un multiple de 5 minutes, de 5 à 30."
        )
    if as_of is not None:
        as_of = as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of.astimezone(UTC)
    try:
        result = service.forecast(
            network_id, as_of=as_of, horizon_min=horizon_min, sensor_ids=sensor_id
        )
    except NetworkNotFound as error:
        raise ProblemError(NOT_FOUND, "Réseau de vitesse inconnu.") from error
    except NoDataBefore as error:
        raise ProblemError(
            NOT_FOUND, "Aucune mesure de ce réseau à cette date ou avant."
        ) from error
    except ModelUnavailable as error:
        raise ProblemError(FORECAST_UNAVAILABLE, str(error)) from error
    return SpeedForecastListResponse(
        network_id=network_id,
        as_of=result.as_of,
        horizon_min=result.horizon_min,
        model=to_card(result.loaded),
        sensors_without_model=result.sensors_without_model,
        items=[
            SensorForecastResponse(
                sensor_id=i.sensor_id,
                target_time=i.target_time,
                predicted_speed_kmh=i.predicted_speed_kmh,
                persistence_speed_kmh=i.persistence_speed_kmh,
                observed_speed_kmh=i.observed_speed_kmh,
            )
            for i in result.items
        ],
    )
