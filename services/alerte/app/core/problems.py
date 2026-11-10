"""Ce que le service d'alerte ajoute au format d'erreur commun de `errors.py`.

`errors.py` est identique à celui de la collecte (`CODE_PARTAGE`). Ce module ajoute :

- trois familles d'erreurs que la collecte n'a pas : jeton absent ou invalide (401), rôle
  insuffisant (403) et transition d'état impossible (409, `INVALID_STATE_TRANSITION`) ;
- la mise au format `Problem` d'une entrée invalide de la requête (422) : un `field` et un
  `message` par erreur, au chemin `query.limit` ou `body.params.min_windows` du contrat, jamais la
  valeur refusée.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import VALIDATION_ERROR, ProblemError, ProblemKind

UNAUTHENTICATED = ProblemKind(401, "UNAUTHENTICATED", "unauthenticated", "Authentification requise")
FORBIDDEN = ProblemKind(403, "FORBIDDEN", "forbidden", "Droit insuffisant")
INVALID_STATE_TRANSITION = ProblemKind(
    409, "INVALID_STATE_TRANSITION", "invalid-state-transition", "Transition d'état impossible"
)

MAX_PROBLEMS = 20  # au-delà, la liste ne dit rien de plus


async def validation_handler(_: Request, error: RequestValidationError) -> JSONResponse:
    problems = [
        {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
        for item in error.errors()
    ]
    noun = "champ invalide" if len(problems) == 1 else "champs invalides"
    detail = f"{len(problems)} {noun}."
    return ProblemError(VALIDATION_ERROR, detail, errors=problems[:MAX_PROBLEMS]).response()


def register_validation(application: FastAPI) -> None:
    application.add_exception_handler(
        RequestValidationError,
        validation_handler,  # type: ignore[arg-type]
    )
