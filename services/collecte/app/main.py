from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deps import close_components
from app.api.v1 import health, measurements
from app.core.config import get_settings
from app.core.errors import register_handlers
from app.core.logs import CorrelationMiddleware, configure_logging
from app.core.redaction import install_redaction
from app.core.unhandled import UnhandledErrorMiddleware

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)
install_redaction()  # dernier filet : aucun secret (adresse MongoDB) dans une ligne de journal


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    close_components()  # ferme le producteur Kafka (envoie ce qui reste) et la connexion MongoDB


# `redirect_slashes=False` : une seule adresse par route, comme dans le service de traitement.
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
app.include_router(health.router, prefix="/api/v1")
app.include_router(measurements.router, prefix="/api/v1")
