"""Alertes : lister, lire avec l'historique, acquitter, résoudre à la main.

Contrat : `alerte.openapi.yaml`.

Les rôles sont ceux du contrat (`x-required-role`) : lire = `viewer`, agir = `operator`. L'acteur
écrit dans l'historique et dans `acknowledged_by` est l'identifiant de l'utilisateur du jeton
(`sub`) : le nom d'utilisateur n'est pas dans le jeton, et la table des utilisateurs appartient à
l'API métier.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from app.api.deps import get_service, get_store
from app.api.mapping import alert_out, decode_cursor, encode_cursor, history_out
from app.api.security import require_role
from app.core.auth import Claims, Role
from app.core.errors import NOT_FOUND, VALIDATION_ERROR, ProblemError
from app.core.problems import INVALID_STATE_TRANSITION
from app.domain.model import Kind, Severity, State, parse_utc
from app.schemas.api import AlertDetailOut, AlertOut, AlertPageOut, Problem, ResolveBody
from app.services.alerts import AlertService
from app.services.ports import AlertFilter, AlertStore, InvalidTransition, NotFound

router = APIRouter(tags=["Alertes"])

UTC_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$"
PROBLEMS = {
    401: {"model": Problem, "description": "Jeton absent, invalide ou expiré ; `UNAUTHENTICATED`."},
    403: {"model": Problem, "description": "Rôle insuffisant ; `FORBIDDEN`."},
    404: {"model": Problem, "description": "Alerte inconnue ; `NOT_FOUND`."},
    409: {"model": Problem, "description": "Alerte déjà résolue ; `INVALID_STATE_TRANSITION`."},
    422: {"model": Problem, "description": "Entrée invalide ; `VALIDATION_ERROR`."},
}


def _responses(*statuses: int) -> dict:
    return {status: PROBLEMS[status] for status in statuses}


def _known_id(alert_id: str) -> str:
    """Un identifiant qui n'est pas un UUID ne peut désigner aucune alerte : 404, pas 422."""
    try:
        return str(uuid.UUID(alert_id))
    except ValueError as error:
        raise ProblemError(NOT_FOUND, "Alerte inconnue.") from error


def _cannot(error: InvalidTransition) -> ProblemError:
    return ProblemError(
        INVALID_STATE_TRANSITION,
        f"L'alerte est à l'état {error.current.value} : le passage à {error.target.value} "
        "est impossible.",
    )


@router.get(
    "/alerts",
    response_model=AlertPageOut,
    operation_id="listAlerts",
    summary="Lister les alertes",
    openapi_extra={"x-required-role": "viewer"},
    responses=_responses(401, 403, 422),
)
def list_alerts(
    _: Annotated[Claims, Depends(require_role(Role.VIEWER))],
    store: Annotated[AlertStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    state: State | None = None,
    kind: Kind | None = None,
    severity: Severity | None = None,
    intersection_id: Annotated[str | None, Query(pattern=r"^INT_[0-9]{2,}$")] = None,
    road_segment_id: Annotated[str | None, Query(pattern=r"^ROAD_[0-9]{3,}$")] = None,
    opened_from: Annotated[str | None, Query(pattern=UTC_PATTERN)] = None,
    opened_to: Annotated[str | None, Query(pattern=UTC_PATTERN)] = None,
) -> dict:
    after = None
    if cursor is not None:
        try:
            after = decode_cursor(cursor)
        except ValueError as error:
            raise ProblemError(
                VALIDATION_ERROR,
                "1 champ invalide.",
                errors=[{"field": "query.cursor", "message": "Curseur invalide."}],
            ) from error
    filters = AlertFilter(
        state=state,
        kind=kind,
        severity=severity.value if severity else None,
        intersection_id=intersection_id,
        road_segment_id=road_segment_id,
        opened_from=_instant(opened_from),
        opened_to=_instant(opened_to),
    )
    page = store.list_alerts(filters, after=after, limit=limit + 1)  # +1 : y a-t-il une suite ?
    items = page[:limit]
    return {
        "items": [alert_out(a) for a in items],
        "next_cursor": encode_cursor(items[-1]) if len(page) > limit else None,
    }


def _instant(value: str | None):  # noqa: ANN202
    return parse_utc(value) if value else None


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertDetailOut,
    operation_id="getAlert",
    summary="Lire une alerte et son historique",
    openapi_extra={"x-required-role": "viewer"},
    responses=_responses(401, 403, 404),
)
def get_alert(
    alert_id: str,
    _: Annotated[Claims, Depends(require_role(Role.VIEWER))],
    store: Annotated[AlertStore, Depends(get_store)],
) -> dict:
    found = store.get_alert(_known_id(alert_id))
    if found is None:
        raise ProblemError(NOT_FOUND, "Alerte inconnue.")
    alert, history = found
    return {**alert_out(alert), "history": [history_out(h) for h in history]}


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertOut,
    operation_id="acknowledgeAlert",
    summary="Acquitter une alerte",
    openapi_extra={"x-required-role": "operator"},
    responses=_responses(401, 403, 404, 409),
)
def acknowledge(
    alert_id: str,
    claims: Annotated[Claims, Depends(require_role(Role.OPERATOR))],
    service: Annotated[AlertService, Depends(get_service)],
) -> dict:
    try:
        alert, _changed = service.acknowledge(_known_id(alert_id), claims.subject)
    except NotFound as error:
        raise ProblemError(NOT_FOUND, "Alerte inconnue.") from error
    except InvalidTransition as error:
        raise _cannot(error) from error
    return alert_out(alert)


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=AlertOut,
    operation_id="resolveAlert",
    summary="Résoudre une alerte à la main",
    openapi_extra={"x-required-role": "operator"},
    responses=_responses(401, 403, 404, 409, 422),
)
def resolve(
    alert_id: str,
    claims: Annotated[Claims, Depends(require_role(Role.OPERATOR))],
    service: Annotated[AlertService, Depends(get_service)],
    body: Annotated[ResolveBody | None, Body()] = None,
) -> dict:
    try:
        alert = service.resolve_manual(
            _known_id(alert_id), claims.subject, body.comment if body else None
        )
    except NotFound as error:
        raise ProblemError(NOT_FOUND, "Alerte inconnue.") from error
    except InvalidTransition as error:
        raise _cannot(error) from error
    return alert_out(alert)
