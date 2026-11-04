from fastapi import FastAPI

from app.api.responses import use_problem_media_type
from app.api.v1 import auth, health, indicators, users
from app.core.audit import AuditMiddleware
from app.core.config import get_settings
from app.core.errors import register_handlers
from app.core.logs import CorrelationMiddleware, configure_logging
from app.core.unhandled import UnhandledErrorMiddleware
from app.core.versioning import API_PREFIX

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)

# `redirect_slashes=False` : `/api/v1/users/` n'est pas `/api/v1/users`. Une redirection 307 que le
# contrat ne documente pas laisserait deux adresses pour une route ; la seconde répond 404.
app = FastAPI(title=settings.app_name, version=settings.app_version, redirect_slashes=False)
# Le dernier ajouté est le plus extérieur. De l'extérieur vers l'intérieur : la corrélation pose
# l'identifiant ; l'audit le lit et voit le code que le client reçoit, 500 compris ; les erreurs
# imprévues sont transformées en 500 `Problem` (voir `app/core/unhandled.py`).
app.add_middleware(UnhandledErrorMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(CorrelationMiddleware)
register_handlers(app)
use_problem_media_type(app)

app.include_router(health.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(indicators.router, prefix=API_PREFIX)
