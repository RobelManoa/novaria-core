"""État des feux, historique et commande manuelle (contrat `reponse.openapi.yaml`).

Lire est permis au `viewer`, commander à l'`operator`. Une commande passe par **les mêmes
garde-fous** que les recommandations : refusée (`422 UNSAFE_COMMAND`, motif précis dans `detail`),
elle n'atteint jamais le contrôleur, mais elle est journalisée et publiée sur `signal.status`.
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.adapters.mongo_audit import InvalidCursor
from app.api.deps import get_audit, get_service
from app.api.mapping import command_out, history_out, state_out
from app.api.security import require_role
from app.core.auth import Claims, Role
from app.core.errors import NOT_FOUND, UPSTREAM_UNAVAILABLE, VALIDATION_ERROR, ProblemError
from app.core.logs import correlation_id_var
from app.core.problems import COMMAND_IN_PROGRESS, RATE_LIMITED, UNSAFE_COMMAND
from app.domain.controller import COMMAND_IN_PROGRESS as IN_PROGRESS_CODE
from app.domain.model import Action, Command, utc_stamp
from app.schemas.api import (
    Problem,
    SignalCommandIn,
    SignalCommandOut,
    SignalCommandPageOut,
    SignalStateListOut,
    SignalStateOut,
)
from app.services.ports import (
    AuditFailed,
    AuditLog,
    CommandNotRecorded,
    RateLimited,
    UnknownIntersection,
)
from app.services.signals import SignalService

router = APIRouter(tags=["Feux"])

INTERSECTION_ID = re.compile(r"^INT_[0-9]{2,}$")
# Le champ du corps que chaque motif de refus met en cause (pour que l'écran le montre).
REFUSED_FIELD = {
    "PHASE_TOO_SHORT": "body.duration_s",
    "PHASE_TOO_LONG": "body.duration_s",
    "UNKNOWN_PHASE": "body.phase_id",
}

AUTH = {
    401: {"model": Problem, "description": "Jeton absent, invalide ou expiré."},
    403: {"model": Problem, "description": "Rôle insuffisant."},
}


def known(intersection_id: str) -> str:
    """Un carrefour mal formé n'existe pas : 404, comme un carrefour sans feux."""
    if not INTERSECTION_ID.fullmatch(intersection_id):
        raise ProblemError(NOT_FOUND, "Carrefour inconnu.")
    return intersection_id


@router.get(
    "/signals",
    response_model=SignalStateListOut,
    operation_id="listSignals",
    summary="État des feux de tous les carrefours équipés",
    openapi_extra={"x-required-role": "viewer"},
    responses=AUTH,
)
def list_signals(
    _: Annotated[Claims, Depends(require_role(Role.VIEWER))],
    service: Annotated[SignalService, Depends(get_service)],
) -> dict:
    return {"items": [state_out(view) for view in service.views()]}


@router.get(
    "/signals/{intersection_id}",
    response_model=SignalStateOut,
    operation_id="getSignal",
    summary="État des feux d'un carrefour",
    openapi_extra={"x-required-role": "viewer"},
    responses={**AUTH, 404: {"model": Problem, "description": "Carrefour sans feux."}},
)
def get_signal(
    intersection_id: str,
    _: Annotated[Claims, Depends(require_role(Role.VIEWER))],
    service: Annotated[SignalService, Depends(get_service)],
) -> dict:
    try:
        return state_out(service.view(known(intersection_id)))
    except UnknownIntersection as error:
        raise ProblemError(NOT_FOUND, "Carrefour inconnu.") from error


@router.get(
    "/signals/{intersection_id}/commands",
    response_model=SignalCommandPageOut,
    operation_id="listSignalCommands",
    summary="Historique des commandes",
    openapi_extra={"x-required-role": "viewer"},
    responses={
        **AUTH,
        404: {"model": Problem, "description": "Carrefour sans feux."},
        422: {"model": Problem, "description": "Entrée invalide ; `VALIDATION_ERROR`."},
        503: {"model": Problem, "description": "Journal d'audit indisponible."},
    },
)
def list_commands(
    intersection_id: str,
    _: Annotated[Claims, Depends(require_role(Role.VIEWER))],
    service: Annotated[SignalService, Depends(get_service)],
    audit: Annotated[AuditLog, Depends(get_audit)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    if not service.knows(known(intersection_id)):
        raise ProblemError(NOT_FOUND, "Carrefour inconnu.")
    try:
        entries, next_cursor = audit.history(intersection_id, limit, cursor)
    except InvalidCursor as error:
        raise ProblemError(
            VALIDATION_ERROR,
            "1 champ invalide.",
            errors=[{"field": "query.cursor", "message": "Curseur invalide."}],
        ) from error
    except AuditFailed as error:
        raise ProblemError(
            UPSTREAM_UNAVAILABLE, "Le journal d'audit est indisponible. Réessayez dans un instant."
        ) from error
    return {"items": [history_out(entry) for entry in entries], "next_cursor": next_cursor}


@router.post(
    "/signals/{intersection_id}/commands",
    response_model=SignalCommandOut,
    status_code=202,
    operation_id="sendSignalCommand",
    summary="Envoyer une commande manuelle",
    openapi_extra={"x-required-role": "operator"},
    responses={
        **AUTH,
        404: {"model": Problem, "description": "Carrefour sans feux."},
        409: {"model": Problem, "description": "Une commande manuelle est en cours."},
        429: {"model": Problem, "description": "Trop de commandes en une minute."},
        422: {"model": Problem, "description": "Corps invalide ou commande dangereuse refusée."},
        503: {"model": Problem, "description": "Journal d'audit indisponible : rien n'a été fait."},
    },
)
def send_command(
    intersection_id: str,
    body: SignalCommandIn,
    claims: Annotated[Claims, Depends(require_role(Role.OPERATOR))],
    response: Response,
    service: Annotated[SignalService, Depends(get_service)],
) -> dict:
    if not service.knows(known(intersection_id)):
        raise ProblemError(NOT_FOUND, "Carrefour inconnu.")
    resume = body.action == "RESUME_AUTOMATIC"
    command = Command(
        command_id=str(uuid.uuid4()),
        action=Action(body.action),
        actor=claims.subject,
        reason=body.reason,
        phase_id=None if resume else body.phase_id,
        duration_s=None if resume else body.duration_s,
    )
    try:
        result = service.command(
            intersection_id,
            command,
            role=claims.role.value,
            correlation_id=correlation_id_var.get(),
        )
    except RateLimited as error:
        raise ProblemError(
            RATE_LIMITED,
            "Trop de commandes en une minute : réessayez dans un instant.",
            headers={"Retry-After": str(error.retry_after_s)},
        ) from error
    except CommandNotRecorded as error:
        raise ProblemError(
            UPSTREAM_UNAVAILABLE,
            "Le journal d'audit est indisponible : la commande n'a pas été appliquée.",
        ) from error
    decision = result.decision
    if decision.refused:
        code = decision.refusal_reason or ""
        in_progress = code == IN_PROGRESS_CODE
        raise ProblemError(
            COMMAND_IN_PROGRESS if in_progress else UNSAFE_COMMAND,
            f"{code} : {decision.detail}",
            errors=None
            if in_progress
            else [{"field": REFUSED_FIELD.get(code, "body"), "message": code}],
        )
    response.headers["Location"] = f"/api/v1/signals/{intersection_id}"
    return command_out(command, decision, intersection_id, utc_stamp(result.at))
