from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api import metrics
from app.api.responses import use_problem_media_type
from app.api.v1 import auth, forecasts, health, indicators, reports, users
from app.core.audit import AuditMiddleware
from app.core.config import Settings, get_settings
from app.core.cors import cors_options
from app.core.errors import register_handlers
from app.core.headers import SecurityHeadersMiddleware
from app.core.logs import CorrelationMiddleware, configure_logging
from app.core.redaction import install_redaction
from app.core.unhandled import UnhandledErrorMiddleware
from app.core.versioning import API_PREFIX


def create_app(settings: Settings) -> FastAPI:
    """L'application, avec la configuration donnée (les tests en construisent plusieurs)."""
    # `redirect_slashes=False` : `/api/v1/users/` n'est pas `/api/v1/users`. Une redirection 307 que
    # le contrat ne documente pas laisserait deux adresses pour une route ; la seconde répond 404.
    application = FastAPI(
        title=settings.app_name, version=settings.app_version, redirect_slashes=False
    )
    # Le dernier ajouté est le plus extérieur. De l'extérieur vers l'intérieur : les en-têtes de
    # sécurité, CORS, la corrélation (pose l'identifiant), l'audit (le lit et voit le code que le
    # client reçoit, 500 compris), les erreurs imprévues (transformées en 500 `Problem`, voir
    # `app/core/unhandled.py`).
    # Sécurité applicative (BE-08) à l'extérieur de tout le reste : une réponse d'erreur, un 429 ou
    # un 500 portent donc aussi les en-têtes de sécurité et, pour une origine autorisée, ceux de
    # CORS. Sans origine configurée, CORS n'est pas monté : aucune origine n'est autorisée.
    application.add_middleware(UnhandledErrorMiddleware)
    application.add_middleware(AuditMiddleware)
    application.add_middleware(CorrelationMiddleware)
    if settings.cors_origins:
        application.add_middleware(CORSMiddleware, **cors_options(settings.cors_origins))
    application.add_middleware(SecurityHeadersMiddleware)
    register_handlers(application)
    use_problem_media_type(application)

    # Point d'exploitation, hors de `/api/v1` et du contrat : ajouté comme route simple.
    application.add_api_route(
        "/metrics", metrics.read_metrics, methods=["GET"], include_in_schema=False
    )
    application.include_router(health.router, prefix=API_PREFIX)
    application.include_router(auth.router, prefix=API_PREFIX)
    application.include_router(users.router, prefix=API_PREFIX)
    application.include_router(indicators.router, prefix=API_PREFIX)
    application.include_router(forecasts.router, prefix=API_PREFIX)
    application.include_router(reports.router, prefix=API_PREFIX)
    return application


settings = get_settings()
configure_logging(settings.service_name, settings.log_level)
install_redaction()  # dernier filet : aucun secret dans une ligne de journal (BE-08)
app = create_app(settings)
