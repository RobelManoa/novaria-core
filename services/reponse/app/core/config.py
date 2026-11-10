import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

JWT_SECRET_MIN_LENGTH = 32
# Valeur d'exemple de `.env.example` : « change-me-local... ». Tolérée en local seulement (BE-08).
PLACEHOLDER = "change-me-local"
INTERSECTION = re.compile(r"INT_[0-9]{2,}")

# Réglages qui portent un secret (adresse de MongoDB avec mot de passe, clé des jetons).
SECRET_SETTINGS = ("mongo_url", "jwt_secret")

TOPIC_RECOMMENDATIONS = "traffic.recommendations"
TOPIC_STATUS = "signal.status"
TOPIC_ERRORS = "errors.dlq"

# Le réseau de démonstration (migration 0005) : six carrefours à quatre approches.
DEFAULT_INTERSECTIONS = "INT_01,INT_02,INT_03,INT_04,INT_05,INT_06"


class Settings(BaseSettings):
    """Configuration lue depuis les variables d'environnement (jamais de secret dans le code).

    `hide_input_in_errors` : une valeur refusée n'est jamais recopiée dans le message d'erreur.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    service_name: str = "reponse"
    app_name: str = "Novaria Core : service reponse"
    app_version: str = "0.1.0"
    environment: str = "local"
    git_sha: str = "dev"  # injecté au build : relie la version déployée à sa révision
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- Journal d'audit : collection `audit_logs` de MongoDB, compte `svc_reponse` (ADR-024). Un
    # secret : pas de valeur par défaut. Sans lui, le journal est indisponible et toute commande
    # manuelle est refusée (503) : on n'agit pas sans trace.
    mongo_url: SecretStr | None = None
    mongo_timeout_ms: int = Field(default=2000, ge=100, le=30000)

    # --- Bus (ADR-009) : adresse du broker Kafka. Vide : le service ne lit ni ne publie rien, les
    # feux tournent au plan fixe.
    kafka_bootstrap_servers: str = ""
    kafka_publish_timeout_s: float = Field(default=10.0, gt=0, le=60)
    kafka_group_id: str = "reponse"  # une seule instance active : l'état des feux est en mémoire
    dispatch_retry_s: float = Field(default=2.0, gt=0, le=60)

    # --- Authentification : clé de signature des jetons émis par l'API métier (BE-03), la même.
    jwt_secret: SecretStr | None = None

    # --- Contrôleur de feux simulé
    signal_intersections: str = DEFAULT_INTERSECTIONS
    fixed_phase_s: int = Field(default=30, ge=1, le=600)  # durée de chaque phase du plan fixe
    # Silence maximal avant le retour au plan fixe : une recommandation vaut au plus ce délai à
    # partir de sa réception, même si son `valid_until` est plus lointain (le traitement en publie
    # une par minute tant que la dégradation dure : trois manquées, c'est une perte).
    max_silence_s: int = Field(default=180, ge=5, le=3600)
    # Commandes manuelles par opérateur et par minute (refus compris) : on ne martèle pas les feux.
    command_rate_per_min: int = Field(default=10, ge=1, le=600)
    tick_interval_s: float = Field(default=0.5, gt=0, le=10)
    # Origine annoncée tant qu'aucune recommandation n'a fixé la provenance (démarrage, plan fixe).
    default_run_id: str = Field(default="reponse", min_length=1, max_length=80)
    default_scenario_id: str = Field(default="plan-fixe", pattern=r"^[a-z0-9_-]{1,60}$")
    default_seed: int = Field(default=0, ge=0)

    @field_validator("mongo_url", "jwt_secret", mode="before")
    @classmethod
    def empty_means_not_configured(cls, value: object) -> object:
        """Docker Compose passe une variable non définie sous la forme d'une chaîne vide."""
        return None if value == "" else value

    @field_validator("jwt_secret")
    @classmethod
    def secret_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        """Une clé trop courte se devine : refusée au démarrage plutôt que découverte plus tard."""
        if value is not None and len(value.get_secret_value()) < JWT_SECRET_MIN_LENGTH:
            raise ValueError(f"JWT_SECRET doit avoir au moins {JWT_SECRET_MIN_LENGTH} caractères")
        return value

    @field_validator("signal_intersections")
    @classmethod
    def intersections_are_well_formed(cls, value: str) -> str:
        names = [name.strip() for name in value.split(",") if name.strip()]
        if not names or any(not INTERSECTION.fullmatch(name) for name in names):
            raise ValueError(
                "SIGNAL_INTERSECTIONS : des identifiants INT_nn séparés par des virgules"
            )
        return ",".join(dict.fromkeys(names))

    @model_validator(mode="after")
    def example_values_are_local_only(self) -> "Settings":
        """Hors local, la valeur d'exemple de `.env.example` n'est pas un secret : refusée."""
        if self.environment == "local":
            return self
        for name in SECRET_SETTINGS:
            value = getattr(self, name)
            if value is not None and PLACEHOLDER in value.get_secret_value():
                raise ValueError(
                    f"{name.upper()} porte la valeur d'exemple de .env.example : "
                    "à remplacer hors de l'environnement local"
                )
        return self

    @property
    def intersections(self) -> list[str]:
        return self.signal_intersections.split(",")


@lru_cache
def get_settings() -> Settings:
    return Settings()
