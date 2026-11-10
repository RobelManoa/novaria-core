"""Flux d'événements en direct, `GET /api/v1/events/stream` (SSE, voir `app/sse.py`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_hub
from app.api.security import require_role
from app.core.auth import Claims, Role
from app.core.config import Settings, get_settings
from app.core.errors import VALIDATION_ERROR, ProblemError
from app.schemas.api import Problem
from app.sse import ALERT_EVENT, EventHub, stream

router = APIRouter(tags=["Flux"])

# `signal.status` vient du service de réponse (MS-12) : accepté dans le filtre, rien à diffuser tant
# que ce service ne publie pas.
KNOWN_TYPES = frozenset({ALERT_EVENT, "signal.status"})


@router.get(
    "/events/stream",
    operation_id="streamEvents",
    summary="Flux d'événements en direct (SSE)",
    openapi_extra={"x-required-role": "viewer"},
    response_class=StreamingResponse,
    responses={
        200: {"description": "Flux ouvert.", "content": {"text/event-stream": {}}},
        401: {"model": Problem, "description": "Jeton absent, invalide ou expiré."},
        403: {"model": Problem, "description": "Rôle insuffisant."},
    },
)
async def stream_events(
    _: Annotated[Claims, Depends(require_role(Role.VIEWER))],
    hub: Annotated[EventHub, Depends(get_hub)],
    settings: Annotated[Settings, Depends(get_settings)],
    types: Annotated[str | None, Query(max_length=200)] = None,
) -> StreamingResponse:
    wanted: frozenset[str] | None = None
    if types:
        names = frozenset(part.strip() for part in types.split(",") if part.strip())
        unknown = sorted(names - KNOWN_TYPES)
        if unknown:
            raise ProblemError(
                VALIDATION_ERROR,
                "1 champ invalide.",
                errors=[
                    {
                        "field": "query.types",
                        "message": f"Type inconnu : {', '.join(unknown)[:100]}.",
                    }
                ],
            )
        wanted = names or None
    return StreamingResponse(
        stream(hub, wanted, settings.sse_heartbeat_s),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
