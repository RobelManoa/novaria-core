from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.guards import refresh_circuits
from app.api.deps import close_components, get_components
from app.api.v1 import health, measurements
from app.core.config import get_settings
from app.core.errors import register_handlers
from app.core.logs import CorrelationMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, metrics_response
from app.core.redaction import install_redaction
from app.core.unhandled import UnhandledErrorMiddleware

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)
install_redaction()  # dernier filet : aucun secret (adresse MongoDB) dans une ligne de journal


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_components()  # les disjoncteurs existent (et se voient dans /metrics) dès le démarrage
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
# Le plus extérieur : compte aussi les 500 transformés par l'intergiciel d'erreurs.
app.add_middleware(MetricsMiddleware, service=settings.service_name)
register_handlers(app)


# Point d'exploitation (MS-16) : hors de `/api/v1`, hors du contrat, non routé par la passerelle.
def read_metrics():
    refresh_circuits()  # l'état d'un disjoncteur dépend aussi du temps écoulé
    return metrics_response()


app.add_api_route("/metrics", read_metrics, methods=["GET"], include_in_schema=False)
app.include_router(health.router, prefix="/api/v1")
app.include_router(measurements.router, prefix="/api/v1")
