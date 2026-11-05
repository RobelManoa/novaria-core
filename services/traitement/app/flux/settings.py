"""Configuration du service de flux, lue dans l'environnement (jamais de secret dans le code).

Distincte de celle de l'API (`app/core/config.py`) : le flux n'a besoin ni du secret des jetons ni
de la base `app`. Les variables sont celles que Docker Compose fournit déjà au service traitement.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class FluxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    kafka_bootstrap_servers: str = "localhost:9094"
    postgres_url: SecretStr  # compte svc_traitement (entrepôt dwh)
    mongo_url: SecretStr  # compte svc_traitement (rejects, processing_stats)
    topic_raw: str = "iot.raw"
    consumer_group: str = "traitement-flux"
    # Rejeu d'un jeu historique : les horodatages passés sont la règle, le futur n'est plus jugé.
    flux_replay: bool = False
    poll_timeout_ms: int = Field(default=1000, ge=50, le=30000)
    poll_max_records: int = Field(default=500, ge=1, le=10000)
    log_level: str = "INFO"
    heartbeat_file: str = "/tmp/flux-alive"  # noqa: S108 - fichier de vie lu par la sonde du conteneur
