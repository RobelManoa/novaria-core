from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deps import close_components, get_components
from app.api.v1 import health, signals
from app.core.config import get_settings
from app.core.errors import register_handlers
from app.core.logs import CorrelationMiddleware, configure_logging
from app.core.problems import register_validation
from app.core.redaction import install_redaction
from app.core.unhandled import UnhandledErrorMiddleware

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)
install_redaction()  # dernier filet : aucun secret (adresse de MongoDB, jeton) dans le journal


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_components().start()  # phases, envoi des événements, lecture des recommandations
    yield
    close_components()  # plan fixe pour tous les carrefours, dit sur le bus avant de partir


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
app.include_router(health.router, prefix="/api/v1")
app.include_router(signals.router, prefix="/api/v1")
