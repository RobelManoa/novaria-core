import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.v1 import auth, health, users
from app.core.config import get_settings
from app.core.errors import (
    PROBLEM_MEDIA_TYPE,
    UPSTREAM_UNAVAILABLE,
    ProblemError,
    problem_handler,
)
from app.core.logs import CorrelationMiddleware, configure_logging

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(CorrelationMiddleware)
app.add_exception_handler(ProblemError, problem_handler)


@app.exception_handler(OperationalError)
async def database_unreachable(_: Request, error: OperationalError) -> JSONResponse:
    """Base injoignable : 503 sans détail (l'adresse, donc le mot de passe, reste cachée)."""
    logging.getLogger("app.db").error(
        "base injoignable", extra={"fields": {"error": type(error.orig).__name__}}
    )
    problem = ProblemError(UPSTREAM_UNAVAILABLE, "La base des comptes est injoignable.")
    return JSONResponse(problem.body(), status_code=503, media_type=PROBLEM_MEDIA_TYPE)


app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
