import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

JWT_SECRET_MIN_LENGTH = 32
# Valeur d'exemple de `.env.example` : « change-me-local... ». Tolérée en local seulement.
PLACEHOLDER = "change-me-local"
# Réglages qui portent un secret (une valeur, ou une adresse de connexion avec son mot de passe).
SECRET_SETTINGS = ("jwt_secret", "app_database_url", "postgres_url", "audit_mongo_url")
# Origine d'un navigateur : schéma, hôte, port facultatif, rien d'autre (ni chemin, ni `*`).
ORIGIN_PATTERN = re.compile(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?")


class Settings(BaseSettings):
    """Configuration lue depuis les variables d'environnement (jamais de secret dans le code).

    `hide_input_in_errors` : une valeur refusée n'est jamais recopiée dans le message d'erreur
    (sinon un secret trop court finirait dans le journal de démarrage).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

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

    # --- Journal d'audit et compteurs d'usage (BE-05) : MongoDB, compte `svc_backend`.
    # Sans cette adresse, l'API répond normalement mais n'écrit ni audit ni compteur (un
    # avertissement est journalisé au premier appel).
    audit_mongo_url: SecretStr | None = None

    # --- Sécurité applicative (BE-08) -----------------------------------------------------------
    # Origines de navigateur autorisées à lire les réponses (CORS), séparées par des virgules.
    # Vide : aucune origine, donc aucun en-tête CORS (le navigateur n'autorise que la même
    # origine).
    cors_allowed_origins: str = ""
    # Limitation de la connexion : essais par minute et par adresse du client (tous comptes
    # confondus)...
    login_attempts_per_minute: int = Field(default=10, ge=1, le=1000)
    # ... et échecs tolérés par identifiant, sur la durée de blocage qui suit le dernier échec.
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_lockout_s: int = Field(default=900, ge=10, le=86400)
    # Nombre de relais de confiance devant le service (la passerelle : 1). À 0, l'adresse du client
    # est celle de la connexion et `X-Forwarded-For` est ignoré : un client ne peut pas la
    # falsifier.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    @field_validator("jwt_secret")
    @classmethod
    def secret_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        """Un secret trop court se devine : refusé au démarrage plutôt que découvert plus tard."""
        if value is not None and len(value.get_secret_value()) < JWT_SECRET_MIN_LENGTH:
            raise ValueError(f"JWT_SECRET doit avoir au moins {JWT_SECRET_MIN_LENGTH} caractères")
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def origins_are_explicit(cls, value: str) -> str:
        """Pas de `*`, pas de chemin : une origine exacte par entrée."""
        for origin in split_origins(value):
            if not ORIGIN_PATTERN.fullmatch(origin):
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS : chaque origine s'écrit schéma://hôte[:port], "
                    "sans chemin ni joker"
                )
        return value

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
                    f"à remplacer hors de l'environnement local"
                )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return split_origins(self.cors_allowed_origins)


def split_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
