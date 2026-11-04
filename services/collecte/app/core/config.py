from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Réglages qui portent un secret (adresse de connexion avec son mot de passe).
SECRET_SETTINGS = ("mongo_url",)


class Settings(BaseSettings):
    """Configuration lue depuis les variables d'environnement (jamais de secret dans le code).

    `hide_input_in_errors` : une valeur refusée n'est jamais recopiée dans le message d'erreur.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    service_name: str = "collecte"
    app_name: str = "Novaria Core : service collecte"
    app_version: str = "0.1.0"
    environment: str = "local"
    git_sha: str = "dev"  # injecté au build : relie la version déployée à sa révision
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- Bus (ADR-009) : adresse du broker Kafka. Vide : la publication répond 503 (rien de perdu).
    kafka_bootstrap_servers: str = ""
    # Attente maximale de l'accusé du broker pour un message (acks=all), en secondes.
    kafka_publish_timeout_s: float = Field(default=10.0, gt=0, le=60)

    # --- Copie brute et archive des rejets : MongoDB, compte `svc_collecte` (droits : raw_events et
    # rejects, find et insert seulement, ADR-024). Aucune valeur par défaut : c'est un secret.
    mongo_url: SecretStr | None = None
    mongo_db: str = "novaria"
    mongo_timeout_ms: int = Field(default=3000, ge=100, le=60000)

    # --- Réception (MS-08)
    # Taille maximale d'un message en octets (une mesure en fait environ 600) : au-delà, rejet.
    max_body_bytes: int = Field(default=65536, ge=1024, le=1_048_576)


@lru_cache
def get_settings() -> Settings:
    return Settings()
