from fastapi import APIRouter

from app.api.responses import errors
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", responses=errors("5XX"))
def health() -> dict[str, str]:
    """Sonde de santé (Docker, pipeline) ; schéma `Health` du contrat OpenAPI."""
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "revision": settings.git_sha,
        "environment": settings.environment,
    }
