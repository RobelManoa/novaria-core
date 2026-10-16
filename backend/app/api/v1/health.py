from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Sonde de santé utilisée par Docker, ECS et le pipeline après déploiement."""
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "revision": settings.git_sha,
        "environment": settings.environment,
    }
