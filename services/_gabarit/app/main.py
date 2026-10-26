from fastapi import FastAPI

from app.api.v1 import health
from app.core.config import get_settings
from app.core.logs import CorrelationMiddleware, configure_logging

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(CorrelationMiddleware)
app.include_router(health.router, prefix="/api/v1")
