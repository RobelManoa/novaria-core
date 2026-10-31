from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

JWT_SECRET_MIN_LENGTH = 32


class Settings(BaseSettings):
    """Configuration lue depuis les variables d'environnement (jamais de secret dans le code)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "traitement"
    app_name: str = "Novaria Core : service traitement"
    app_version: str = "0.1.0"
    environment: str = "local"
    git_sha: str = "dev"  # injecté au build : relie la version déployée à sa révision
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- Authentification (BE-03). Aucune valeur par défaut : sans secret, la connexion répond 503.
    jwt_secret: SecretStr | None = None
    # Durée de vie du jeton d'accès, en secondes (valeur de départ du contrat : 1800).
    access_token_ttl_s: int = Field(default=1800, ge=60, le=86400)

    # --- Base métier : schéma `app`, compte `svc_app` (ADR-024). Même variable que les migrations.
    app_database_url: SecretStr | None = None

    # --- Entrepôt `dwh`, compte `svc_traitement` : l'API de lecture des indicateurs (BE-04)
    # l'ouvre en lecture seule. Variable déjà fournie à ce service par Docker Compose.
    postgres_url: SecretStr | None = None

    @field_validator("jwt_secret")
    @classmethod
    def secret_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        """Un secret trop court se devine : refusé au démarrage plutôt que découvert plus tard."""
        if value is not None and len(value.get_secret_value()) < JWT_SECRET_MIN_LENGTH:
            raise ValueError(f"JWT_SECRET doit avoir au moins {JWT_SECRET_MIN_LENGTH} caractères")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
