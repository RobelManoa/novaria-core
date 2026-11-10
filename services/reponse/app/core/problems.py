"""Ce que le service de réponse ajoute au format d'erreur commun de `errors.py`.

`errors.py` est identique à celui de la collecte (copie, comme dans les autres services). Ce module
ajoute :

- jeton absent ou invalide (401) et rôle insuffisant (403) ;
- les deux refus propres à la commande de feux : une commande **dangereuse** (422,
  `UNSAFE_COMMAND`, le motif précis est dans `detail`) et une commande **déjà en cours** (409,
  `COMMAND_IN_PROGRESS`) ;
- la mise au format `Problem` d'une entrée invalide de la requête (422) : un `field` et un
  `message` par erreur, jamais la valeur refusée.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import VALIDATION_ERROR, ProblemError, ProblemKind

UNAUTHENTICATED = ProblemKind(401, "UNAUTHENTICATED", "unauthenticated", "Authentification requise")
FORBIDDEN = ProblemKind(403, "FORBIDDEN", "forbidden", "Droit insuffisant")
UNSAFE_COMMAND = ProblemKind(
    422, "UNSAFE_COMMAND", "unsafe-command", "Commande refusée par les garde-fous"
)
COMMAND_IN_PROGRESS = ProblemKind(
    409, "COMMAND_IN_PROGRESS", "command-in-progress", "Une commande manuelle est déjà en cours"
)

RATE_LIMITED = ProblemKind(429, "RATE_LIMITED", "rate-limited", "Trop de commandes")

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
