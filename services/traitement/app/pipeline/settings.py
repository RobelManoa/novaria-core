"""Configuration du pipeline d'écriture, lue dans l'environnement (jamais de secret dans le code).

Mêmes variables que le service de flux (Docker Compose les fournit déjà au service traitement) :
`POSTGRES_URL` et `MONGO_URL` sont celles du compte `svc_traitement`, le seul qui écrit.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    kafka_bootstrap_servers: str = "localhost:9094"
    postgres_url: SecretStr  # compte svc_traitement (écriture dans dwh)
    mongo_url: SecretStr  # compte svc_traitement (rejects, processing_stats)
    topic_indicators: str = "traffic.indicators"
    consumer_group: str = "traitement-entrepot"
    poll_timeout_ms: int = Field(default=1000, ge=50, le=30000)
    poll_max_records: int = Field(default=500, ge=1, le=10000)
    log_level: str = "INFO"
    heartbeat_file: str = "/tmp/pipeline-alive"  # noqa: S108 - fichier de vie lu par la sonde du conteneur
