from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Réglages qui portent un secret (adresse de base avec mot de passe, clé des jetons, webhook).
SECRET_SETTINGS = ("postgres_url", "jwt_secret", "webhook_url")

TOPIC_INDICATORS = "traffic.indicators"
TOPIC_ALERTS = "alerts.events"
TOPIC_ERRORS = "errors.dlq"


class Settings(BaseSettings):
    """Configuration lue depuis les variables d'environnement (jamais de secret dans le code).

    `hide_input_in_errors` : une valeur refusée n'est jamais recopiée dans le message d'erreur.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    service_name: str = "alerte"
    app_name: str = "Novaria Core : service alerte"
    app_version: str = "0.1.0"
    environment: str = "local"
    git_sha: str = "dev"  # injecté au build : relie la version déployée à sa révision
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- Base : schéma `alertes` de PostgreSQL, compte `svc_alerte` (ADR-024). Un secret : pas de
    # valeur par défaut. Le schéma « postgresql+psycopg:// » de Compose est accepté (voir `dsn`).
    postgres_url: SecretStr | None = None
    postgres_pool_max: int = Field(default=5, ge=1, le=50)
    postgres_timeout_s: float = Field(default=5.0, gt=0, le=60)

    # --- Bus (ADR-009) : adresse du broker Kafka. Vide : le service ne publie ni ne lit rien.
    kafka_bootstrap_servers: str = ""
    kafka_publish_timeout_s: float = Field(default=10.0, gt=0, le=60)
    # Groupe qui lit `traffic.indicators` : une seule instance active (séries en mémoire).
    kafka_group_id: str = "alerte"

    # --- Authentification : clé de signature des jetons émis par l'API métier (BE-03), la même.
    jwt_secret: SecretStr | None = None

    # --- Boucle du travailleur (python -m app.worker)
    worker_poll_ms: int = Field(
        default=200, ge=10, le=5000
    )  # attente d'un message, et pas de la boîte d'envoi
    outbox_batch: int = Field(default=100, ge=1, le=1000)
    rules_ttl_s: float = Field(default=5.0, ge=0, le=300)  # durée de vie des règles en mémoire
    heartbeat_file: str = ""  # fichier touché à chaque tour : sonde du conteneur

    # --- Notification simulée (aucune donnée personnelle en v1 : RG-23)
    notification_channel: Literal["log", "webhook"] = "log"
    webhook_url: SecretStr | None = None
    notification_timeout_s: float = Field(default=3.0, gt=0, le=30)

    # --- Diffusion en direct (SSE)
    sse_heartbeat_s: float = Field(default=30.0, gt=0, le=300)
    sse_queue_size: int = Field(
        default=200, ge=1, le=10000
    )  # au-delà, le client trop lent est coupé
    sse_enabled: bool = True  # lit `alerts.events` et diffuse ; faux : l'API répond sans flux

    @property
    def dsn(self) -> str | None:
        """Adresse pour `psycopg` : sans le « +psycopg » du schéma de SQLAlchemy."""
        if self.postgres_url is None:
            return None
        return self.postgres_url.get_secret_value().replace(
            "postgresql+psycopg://", "postgresql://", 1
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
