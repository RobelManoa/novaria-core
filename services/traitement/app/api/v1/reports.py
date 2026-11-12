"""Rapports automatiques : `/api/v1/reports` et `/api/v1/reports/{report_id}/content` (FE-06).

Lecture seule, rôle `viewer` au moins. Le robot (IA-07) dépose le PDF et ses métadonnées dans le
dossier `REPORTS_DIR` ; cette API ne les écrit pas. Paramètres et bornes : `traitement.openapi.yaml`
(section « Proposition (FE-06) », à relire par Daddy).
"""

import uuid
from pathlib import Path
from typing import NoReturn

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.api.deps import require_role
from app.api.responses import errors
from app.core.config import get_settings
from app.core.errors import (
    INTERNAL_ERROR,
    NOT_FOUND,
    UPSTREAM_UNAVAILABLE,
    VALIDATION_ERROR,
    ProblemError,
)
from app.models import Role, User
from app.schemas.reports import ReportPageResponse, ReportResponse
from app.services.reports import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    FileReportStore,
    InvalidCursor,
    ReportCorrupted,
    ReportService,
)

router = APIRouter(prefix="/reports", tags=["reports"])
VIEWER = {"x-required-role": Role.VIEWER.value}


class UnconfiguredStore:
    """Sans `REPORTS_DIR`, chaque lecture répond 503 (après la validation de la requête)."""

    @staticmethod
    def fail() -> NoReturn:
        raise ProblemError(UPSTREAM_UNAVAILABLE, "Le dossier des rapports n'est pas configuré.")

    def list_all(self):
        self.fail()

    def open(self, report_id: uuid.UUID):
        self.fail()


def get_report_service() -> ReportService:
    directory = get_settings().reports_dir
    return ReportService(FileReportStore(Path(directory)) if directory else UnconfiguredStore())


@router.get(
    "",
    response_model=ReportPageResponse,
    openapi_extra=VIEWER,
    responses=errors(401, 403, 422, "5XX"),
)
def list_reports(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None, max_length=512),
    _: User = Depends(require_role(Role.VIEWER)),
    service: ReportService = Depends(get_report_service),
) -> ReportPageResponse:
    try:
        page = service.list_page(limit=limit, cursor=cursor)
    except InvalidCursor as error:
        raise ProblemError(
            VALIDATION_ERROR,
            "1 champ invalide.",
            errors=[{"field": "query.cursor", "message": "Curseur inconnu."}],
        ) from error
    return ReportPageResponse(
        items=[ReportResponse.model_validate(item.model_dump()) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/{report_id}/content",
    response_class=FileResponse,
    openapi_extra=VIEWER,
    responses={
        200: {"description": "Le PDF.", "content": {"application/pdf": {}}},
        **errors(401, 403, 404, 422, "5XX"),
    },
)
def download_report(
    report_id: uuid.UUID,
    _: User = Depends(require_role(Role.VIEWER)),
    service: ReportService = Depends(get_report_service),
) -> FileResponse:
    try:
        report = service.open(report_id)
    except ReportCorrupted as error:
        raise ProblemError(
            INTERNAL_ERROR, "Le fichier du rapport ne correspond pas à son empreinte."
        ) from error
    if report is None:
        raise ProblemError(NOT_FOUND, "Rapport inconnu.")
    return FileResponse(
        report.path,
        media_type=report.metadata.content_type,
        filename=report.metadata.file_name,
        content_disposition_type="attachment",
    )
