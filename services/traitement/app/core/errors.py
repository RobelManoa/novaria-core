"""Erreurs de l'API au format `application/problem+json` (RFC 9457) du contrat OpenAPI.

Corps : `type`, `title`, `status`, `code`, `detail`, `correlation_id` (schéma `Problem` de
`contracts/openapi/common.yaml`). Le détail ne contient ni secret ni trace d'exécution.
Toute erreur de l'API passe par ici (BE-06) : celles que le code lève (`ProblemError`), la
validation Pydantic, les erreurs HTTP du cadre (route inconnue, méthode non permise), une base
injoignable et, dans `app/core/unhandled.py`, les erreurs imprévues. Aucune ne garde le format par
défaut de FastAPI.
"""

import logging
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as HttpError

from app.core.logs import correlation_id_var
from app.core.routing import allowed_methods
from app.core.versioning import SUPPORTED_VERSIONS, unsupported_version

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
METHOD_NOT_ALLOWED = ProblemKind(
    405, "METHOD_NOT_ALLOWED", "method-not-allowed", "Méthode non permise"
)
CONFLICT = ProblemKind(409, "CONFLICT", "conflict", "Conflit")
VALIDATION_ERROR = ProblemKind(422, "VALIDATION_ERROR", "validation-error", "Entrée invalide")
RATE_LIMITED = ProblemKind(429, "RATE_LIMITED", "rate-limited", "Trop de requêtes")
INTERNAL_ERROR = ProblemKind(500, "INTERNAL_ERROR", "internal-error", "Erreur interne")
UPSTREAM_UNAVAILABLE = ProblemKind(
    503, "UPSTREAM_UNAVAILABLE", "upstream-unavailable", "Service indisponible"
)
FORECAST_UNAVAILABLE = ProblemKind(
    503, "FORECAST_UNAVAILABLE", "forecast-unavailable", "Prévision indisponible"
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


# --- Validation Pydantic -------------------------------------------------------------------------


def french_message(error: dict) -> str:
    """Message pour une personne, sans reprendre la valeur saisie (peut-être un mot de passe)."""
    context = error.get("ctx", {})
    match error["type"]:
        case "missing":
            return "Champ obligatoire."
        case "string_too_short":
            return f"Au moins {context.get('min_length')} caractères."
        case "string_too_long":
            return f"Au plus {context.get('max_length')} caractères."
        case "too_short":
            return f"Au moins {context.get('min_length')} éléments."
        case "too_long":
            return f"Au plus {context.get('max_length')} éléments."
        case "string_pattern_mismatch":
            return "Format invalide."
        case "greater_than_equal":
            return f"Doit être supérieur ou égal à {context.get('ge')}."
        case "greater_than":
            return f"Doit être strictement supérieur à {context.get('gt')}."
        case "less_than_equal":
            return f"Doit être inférieur ou égal à {context.get('le')}."
        case "less_than":
            return f"Doit être strictement inférieur à {context.get('lt')}."
        case "literal_error" | "enum":
            return f"Valeur non admise : {context.get('expected', 'voir le contrat')}."
        case "int_parsing" | "int_from_float" | "int_type":
            return "Entier attendu."
        case "float_parsing" | "float_type":
            return "Nombre attendu."
        case "bool_parsing" | "bool_type":
            return "Booléen attendu (true ou false)."
        case "string_type":
            return "Texte attendu."
        case "datetime_parsing" | "datetime_from_date_parsing" | "datetime_type":
            return "Date et heure ISO 8601 attendues."
        case "model_type" | "dict_type" | "model_attributes_type":
            return "Objet JSON attendu."
        case "list_type":
            return "Liste attendue."
        case "extra_forbidden":
            return "Champ non prévu."
        case "uuid_parsing" | "uuid_type":
            return "Identifiant UUID attendu."
        case "json_invalid":
            return "JSON invalide."
        case _:
            return "Valeur invalide."


def field_path(error: dict) -> str:
    """`body.password`, `query.limit`, `path.user_id` ; un JSON illisible désigne `body`."""
    if error["type"] == "json_invalid":
        return "body"
    return ".".join(str(part) for part in error["loc"])


def validation_problem(error: RequestValidationError) -> ProblemError:
    fields = [
        {"field": field_path(item), "message": french_message(item)} for item in error.errors()
    ]
    plural = "s" if len(fields) > 1 else ""
    return ProblemError(
        VALIDATION_ERROR, f"{len(fields)} champ{plural} invalide{plural}.", errors=fields
    )


async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    return await problem_handler(request, validation_problem(error))


# --- Erreurs HTTP du cadre : route inconnue, méthode non permise, version inconnue ---------------

_BY_STATUS: dict[int, tuple[ProblemKind, str]] = {
    401: (UNAUTHENTICATED, "Jeton absent, invalide ou expiré."),
    403: (FORBIDDEN, "Droit insuffisant pour cette opération."),
    404: (NOT_FOUND, "Cette route n'existe pas."),
    405: (METHOD_NOT_ALLOWED, "Méthode non permise pour cette route."),
    409: (CONFLICT, "Conflit avec l'état de la ressource."),
    429: (RATE_LIMITED, "Trop de requêtes."),
}


def http_problem(request: Request, error: HttpError) -> ProblemError:
    """Traduit une erreur HTTP du cadre. Le texte reçu (en anglais) n'est jamais repris."""
    headers = dict(error.headers or {})
    status = error.status_code
    if status == 405 and (methods := allowed_methods(request.scope)):
        headers["Allow"] = ", ".join(methods)  # toutes les méthodes du chemin, pas la première
    version = unsupported_version(request.url.path) if status == 404 else None
    if version is not None:
        published = ", ".join(SUPPORTED_VERSIONS)
        detail = (
            f"Version d'API non prise en charge : {version}. Versions disponibles : {published}."
        )
        return ProblemError(NOT_FOUND, detail)
    if status in _BY_STATUS:
        kind, detail = _BY_STATUS[status]
        return ProblemError(kind, detail, headers=headers)
    base, detail = (
        (INTERNAL_ERROR, "Erreur interne.")
        if status >= 500
        else (VALIDATION_ERROR, "Requête refusée.")
    )
    kind = ProblemKind(status, base.code, base.slug, base.title)
    return ProblemError(kind, detail, headers=headers)


async def http_handler(request: Request, error: HttpError) -> JSONResponse:
    return await problem_handler(request, http_problem(request, error))


# --- Base injoignable ----------------------------------------------------------------------------


async def database_handler(
    request: Request, error: OperationalError | PoolTimeoutError
) -> JSONResponse:
    """Base injoignable ou saturée : 503 sans détail (adresse et mot de passe restent cachés)."""
    cause = getattr(error, "orig", None) or error
    logging.getLogger("app.db").error(
        "base injoignable", extra={"fields": {"error": type(cause).__name__}}
    )
    problem = ProblemError(UPSTREAM_UNAVAILABLE, "Une base de données est injoignable.")
    return await problem_handler(request, problem)


def register_handlers(application: FastAPI) -> None:
    """Branche tous les gestionnaires d'erreurs sur l'application."""
    application.add_exception_handler(ProblemError, problem_handler)
    application.add_exception_handler(RequestValidationError, validation_handler)
    application.add_exception_handler(HttpError, http_handler)
    application.add_exception_handler(OperationalError, database_handler)
    application.add_exception_handler(PoolTimeoutError, database_handler)
