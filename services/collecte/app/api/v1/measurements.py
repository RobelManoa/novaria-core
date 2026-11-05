"""Réception HTTP des mesures : `POST /api/v1/measurements` (MS-08, `collecte.openapi.yaml`).

- Mesure conforme et nouvelle : `202` `ACCEPTED` ; publiée sur `iot.raw`, copie dans `raw_events`
- Même `id` déjà reçu : `202` `DUPLICATE` ; ignorée, journalisée
- Mesure hors contrat : `422` `VALIDATION_ERROR` (champ fautif et motif) ; envoyée sur `errors.dlq`,
  copie dans `rejects`
- Bus ou base indisponible : `503` `UPSTREAM_UNAVAILABLE` ; rien n'est perdu : l'émetteur renvoie

Le corps est lu **tel quel** (octets), pas par FastAPI : un JSON illisible doit rester illisible
dans `errors.dlq`, pas être remplacé par une erreur de cadre. Sa taille est bornée
(`MAX_BODY_BYTES`).
"""

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_ingestion_service
from app.core.config import Settings, get_settings
from app.core.errors import UPSTREAM_UNAVAILABLE, VALIDATION_ERROR, ProblemError
from app.core.logs import correlation_id_var
from app.schemas.measurements import MeasurementReceipt, Problem
from app.services.ingestion import IngestionService, PublishFailed, StoreFailed

router = APIRouter(tags=["measurements"])

MAX_PROBLEMS = 20
MAX_MESSAGE_CHARS = 300


async def read_limited(request: Request, limit: int) -> bytes:
    """Les `limit + 1` premiers octets du corps au plus : assez pour savoir que c'est trop gros."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            break
    return b"".join(chunks)[: limit + 1]


@router.post(
    "/measurements",
    status_code=202,
    response_model=MeasurementReceipt,
    responses={
        422: {"model": Problem, "description": "Mesure hors contrat ; envoyée sur `errors.dlq`."},
        "5XX": {"model": Problem, "description": "Bus ou base injoignable ; renvoyer la mesure."},
    },
)
async def ingest_measurement(
    request: Request,
    service: IngestionService = Depends(get_ingestion_service),
    settings: Settings = Depends(get_settings),
) -> MeasurementReceipt:
    """Dépose une mesure : l'événement complet `novaria.iot.measurement.v1`."""
    body = await read_limited(request, settings.max_body_bytes)
    try:
        receipt = await run_in_threadpool(
            service.receive, body, correlation_id=correlation_id_var.get()
        )
    except (PublishFailed, StoreFailed) as error:
        raise ProblemError(
            UPSTREAM_UNAVAILABLE,
            "Le bus ou la base est injoignable : la mesure n'a pas été traitée, la renvoyer.",
        ) from error
    if receipt.rejection is not None:
        problems = [
            {"field": item["field"], "message": item["message"][:MAX_MESSAGE_CHARS]}
            for item in receipt.rejection.errors[:MAX_PROBLEMS]
        ]
        raise ProblemError(
            VALIDATION_ERROR,
            f"Mesure refusée ({receipt.rejection.reason_code}) : envoyée sur errors.dlq.",
            errors=problems,
        )
    return MeasurementReceipt(event_id=receipt.event_id or "", status=receipt.outcome.value)
