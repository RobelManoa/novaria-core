from fastapi import FastAPI

from app.api.v1 import health
from app.core.config import get_settings
from app.core.logs import CorrelationMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, metrics_response

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(CorrelationMiddleware)
# Le plus extérieur : compte aussi les 500 transformés par l'intergiciel d'erreurs.
app.add_middleware(MetricsMiddleware, service=settings.service_name)

# Point d'exploitation (MS-16) : hors de `/api/v1`, hors du contrat, non routé par la passerelle.
app.add_api_route("/metrics", lambda: metrics_response(), methods=["GET"], include_in_schema=False)
app.include_router(health.router, prefix="/api/v1")
