from fastapi import FastAPI

from app.api.v1 import health
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.include_router(health.router, prefix="/api/v1")
