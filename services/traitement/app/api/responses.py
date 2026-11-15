"""Erreurs documentées de chaque route, telles que le contrat les liste (BE-06).

`errors(401, 403, 422)` donne le paramètre `responses=` d'une route : FastAPI les écrit dans
`/openapi.json` avec le schéma `Problem`. `ServerError` du contrat est écrit `5XX`. Un test compare,
route par route, ces codes à ceux de `contracts/openapi/` : une erreur documentée dans le contrat et
absente ici (ou l'inverse) fait échouer la suite.
"""

from typing import Any

from fastapi import FastAPI

from app.core.errors import PROBLEM_MEDIA_TYPE
from app.schemas.errors import Problem

DESCRIPTIONS: dict[int | str, str] = {
    401: "Jeton absent, invalide ou expiré ; `UNAUTHENTICATED` (`INVALID_CREDENTIALS` au login).",
    403: "Rôle insuffisant pour cette opération ; code `FORBIDDEN`.",
    404: "Ressource inconnue ; code `NOT_FOUND`.",
    409: "Conflit avec l'état de la ressource ; code `CONFLICT`.",
    422: "Entrée invalide ; code `VALIDATION_ERROR`. `errors` liste chaque champ fautif.",
    429: "Limite de débit atteinte ; code `RATE_LIMITED`.",
    503: "Modèle et référence indisponibles ; code `FORECAST_UNAVAILABLE`.",
    "5XX": "Erreur interne ou base injoignable ; code `INTERNAL_ERROR` ou `UPSTREAM_UNAVAILABLE`.",
}


# En-têtes que le contrat attache à une réponse d'erreur (`Retry-After` du 429, `common.yaml`).
HEADERS: dict[int | str, dict[str, Any]] = {
    429: {
        "Retry-After": {
            "description": "Secondes à attendre avant de réessayer.",
            "schema": {"type": "integer", "minimum": 1},
        }
    },
}


def errors(*statuses: int | str) -> dict[int | str, dict[str, Any]]:
    """Réponses d'erreur à déclarer sur une route, par code HTTP (ou `"5XX"`)."""
    return {
        status: {
            "model": Problem,
            "description": DESCRIPTIONS[status],
            **({"headers": HEADERS[status]} if status in HEADERS else {}),
        }
        for status in statuses
    }


def use_problem_media_type(application: FastAPI) -> None:
    """Écrit `application/problem+json` (et non `application/json`) pour les erreurs.

    FastAPI nomme `application/json` le contenu d'une réponse déclarée avec un modèle ; les corps
    d'erreur réels sont en `application/problem+json`.
    """
    default_openapi = application.openapi

    def openapi() -> dict[str, Any]:
        schema = default_openapi()
        for operations in schema["paths"].values():
            for operation in operations.values():
                responses = operation["responses"]
                if "HTTPValidationError" in str(responses.get("422")):
                    del responses["422"]  # ajouté d'office par FastAPI, format que l'API n'émet pas
                for status, response in responses.items():
                    content = response.get("content", {})
                    if status.startswith(("4", "5")) and "application/json" in content:
                        content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
        for unused in ("HTTPValidationError", "ValidationError"):
            schema.get("components", {}).get("schemas", {}).pop(unused, None)
        return schema

    application.openapi = openapi  # type: ignore[method-assign]
