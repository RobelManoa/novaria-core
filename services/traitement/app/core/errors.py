"""Erreurs de l'API au format `application/problem+json` (RFC 9457) du contrat OpenAPI.

Corps : `type`, `title`, `status`, `code`, `detail`, `correlation_id` (schéma `Problem` de
`contracts/openapi/common.yaml`). Le détail ne contient ni secret ni trace d'exécution.
Seules les erreurs d'authentification et de comptes passent ici pour l'instant ; le gestionnaire
général (validation, 404, 500) est l'objet de BE-06.
"""

from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logs import correlation_id_var

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_BASE = "https://novaria.local/problems"


@dataclass(frozen=True)
class ProblemKind:
    status: int
    code: str
    slug: str
    title: str


UNAUTHENTICATED = ProblemKind(401, "UNAUTHENTICATED", "unauthenticated", "Authentification requise")
INVALID_CREDENTIALS = ProblemKind(
    401, "INVALID_CREDENTIALS", "invalid-credentials", "Identifiants invalides"
)
FORBIDDEN = ProblemKind(403, "FORBIDDEN", "forbidden", "Droit insuffisant")
NOT_FOUND = ProblemKind(404, "NOT_FOUND", "not-found", "Ressource inconnue")
CONFLICT = ProblemKind(409, "CONFLICT", "conflict", "Conflit")
VALIDATION_ERROR = ProblemKind(422, "VALIDATION_ERROR", "validation-error", "Entrée invalide")
UPSTREAM_UNAVAILABLE = ProblemKind(
    503, "UPSTREAM_UNAVAILABLE", "upstream-unavailable", "Service indisponible"
)


@dataclass(eq=False)
class ProblemError(Exception):
    """Une erreur que le client doit voir, avec son code HTTP et son code stable."""

    kind: ProblemKind
    detail: str
    headers: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, str]] | None = None

    def body(self) -> dict:
        body: dict = {
            "type": f"{PROBLEM_BASE}/{self.kind.slug}",
            "title": self.kind.title,
            "status": self.kind.status,
            "code": self.kind.code,
            "detail": self.detail,
            "correlation_id": correlation_id_var.get(),
        }
        if self.errors:
            body["errors"] = self.errors
        return body


async def problem_handler(_: Request, error: ProblemError) -> JSONResponse:
    return JSONResponse(
        error.body(),
        status_code=error.kind.status,
        headers=error.headers,
        media_type=PROBLEM_MEDIA_TYPE,
    )
