from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration lue depuis les variables d'environnement (jamais de secret dans le code)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "reponse"
    app_name: str = "Novaria Core : service reponse"
    app_version: str = "0.1.0"
    environment: str = "local"
    git_sha: str = "dev"  # injecté au build : relie la version déployée à sa révision
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
