"""Erreurs de l'API au format `application/problem+json` (RFC 9457), schéma `Problem` du contrat.

Corps : `type`, `title`, `status`, `code`, `detail`, `correlation_id` et, pour une validation,
`errors` (un `field` et un `message` par défaut). Le détail ne contient ni secret ni trace
d'exécution.
"""

from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as HttpError

from app.core.logs import correlation_id_var

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_BASE = "https://novaria.local/problems"
MAX_PROBLEMS = 20  # au-delà, la liste ne dit rien de plus


@dataclass(frozen=True)
class ProblemKind:
    status: int
    code: str
    slug: str
    title: str


VALIDATION_ERROR = ProblemKind(422, "VALIDATION_ERROR", "validation-error", "Entrée invalide")
UNAUTHENTICATED = ProblemKind(401, "UNAUTHENTICATED", "unauthenticated", "Authentification requise")
FORBIDDEN = ProblemKind(403, "FORBIDDEN", "forbidden", "Droit insuffisant")
INVALID_STATE_TRANSITION = ProblemKind(
    409, "INVALID_STATE_TRANSITION", "invalid-state-transition", "Transition d'état impossible"
)
NOT_FOUND = ProblemKind(404, "NOT_FOUND", "not-found", "Ressource inconnue")
METHOD_NOT_ALLOWED = ProblemKind(
    405, "METHOD_NOT_ALLOWED", "method-not-allowed", "Méthode non permise"
)
INTERNAL_ERROR = ProblemKind(500, "INTERNAL_ERROR", "internal-error", "Erreur interne")
UPSTREAM_UNAVAILABLE = ProblemKind(
    503, "UPSTREAM_UNAVAILABLE", "upstream-unavailable", "Service indisponible"
)


@dataclass(eq=False)
class ProblemError(Exception):
    """Une erreur que le client doit voir, avec son code HTTP et son code stable."""

    kind: ProblemKind
    detail: str
    errors: list[dict[str, str]] | None = None
    headers: dict[str, str] = field(default_factory=dict)

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

    def response(self) -> JSONResponse:
        return JSONResponse(
            self.body(),
            status_code=self.kind.status,
            headers=self.headers,
            media_type=PROBLEM_MEDIA_TYPE,
        )


async def problem_handler(_: Request, error: ProblemError) -> JSONResponse:
    return error.response()


async def http_error_handler(_: Request, error: HttpError) -> JSONResponse:
    """Route inconnue, méthode non permise : le texte du cadre n'est jamais repris."""
    kind = {404: NOT_FOUND, 405: METHOD_NOT_ALLOWED}.get(error.status_code)
    if kind is None:
        kind = INTERNAL_ERROR if error.status_code >= 500 else VALIDATION_ERROR
        detail = "Erreur interne." if error.status_code >= 500 else "Requête refusée."
        return ProblemError(
            ProblemKind(error.status_code, kind.code, kind.slug, kind.title), detail
        ).response()
    detail = "Aucune route ne correspond." if kind is NOT_FOUND else "Méthode non permise."
    return ProblemError(kind, detail, headers=dict(error.headers or {})).response()


async def validation_handler(_: Request, error: RequestValidationError) -> JSONResponse:
    """Entrée invalide : un `field` et un `message` par erreur, jamais la valeur refusée."""
    problems = [
        {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
        for item in error.errors()
    ]
    noun = "champ invalide" if len(problems) == 1 else "champs invalides"
    detail = f"{len(problems)} {noun}."
    return ProblemError(VALIDATION_ERROR, detail, errors=problems[:MAX_PROBLEMS]).response()


def register_handlers(application: FastAPI) -> None:
    application.add_exception_handler(ProblemError, problem_handler)  # type: ignore[arg-type]
    application.add_exception_handler(
        RequestValidationError,
        validation_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(HttpError, http_error_handler)  # type: ignore[arg-type]
