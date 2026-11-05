from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.deps import close_components, get_components
from app.api.v1 import alerts, health, rules, stream
from app.core.config import get_settings
from app.core.errors import UPSTREAM_UNAVAILABLE, ProblemError, register_handlers
from app.core.logs import CorrelationMiddleware, configure_logging
from app.core.problems import register_validation
from app.core.redaction import install_redaction
from app.core.unhandled import UnhandledErrorMiddleware
from app.services.ports import StoreFailed

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)
install_redaction()  # dernier filet : aucun secret (adresse de base, jeton) dans le journal


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_components().start()  # lecteur de alerts.events : la diffusion en direct
    yield
    close_components()


async def store_failed_handler(_: Request, error: StoreFailed) -> JSONResponse:
    """La base ne répond pas : 503, sans détail technique. Aucune écriture n'a eu lieu."""
    return ProblemError(
        UPSTREAM_UNAVAILABLE, "La base des alertes est indisponible. Réessayez dans un instant."
    ).response()


# `redirect_slashes=False` : une seule adresse par route, comme dans les autres services.
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    redirect_slashes=False,
    lifespan=lifespan,
)
# Le dernier ajouté est le plus extérieur : la corrélation pose l'identifiant, puis les erreurs
# imprévues sont transformées en 500 `Problem` qui le portent.
app.add_middleware(UnhandledErrorMiddleware)
app.add_middleware(CorrelationMiddleware)
register_handlers(app)
register_validation(app)
app.add_exception_handler(StoreFailed, store_failed_handler)  # type: ignore[arg-type]
app.include_router(health.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(rules.router, prefix="/api/v1")
app.include_router(stream.router, prefix="/api/v1")
