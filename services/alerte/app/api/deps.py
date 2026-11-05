"""Composants de l'API (base, cycle de vie, diffusion) et dépendances d'authentification.

Les composants sont créés à la demande, une fois par processus. Sans `POSTGRES_URL`, les routes qui
touchent la base répondent 503 (`UPSTREAM_UNAVAILABLE`) au lieu d'empêcher le service de démarrer :
la sonde de santé répond, et l'état se voit. Les tests remplacent ces dépendances par des faux
(`app.dependency_overrides`).
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.adapters.kafka_io import EventsReader
from app.adapters.postgres_store import PostgresAlertStore
from app.core.auth import Claims, InvalidToken, Role, decode_token, has_at_least
from app.core.config import TOPIC_ALERTS, Settings, get_settings
from app.core.errors import UPSTREAM_UNAVAILABLE, ProblemError
from app.core.problems import FORBIDDEN, UNAUTHENTICATED
from app.services.alerts import AlertService
from app.services.ports import AlertStore, StoreFailed
from app.sse import EventHub

logger = logging.getLogger("app.deps")

# `auto_error=False` : l'erreur est produite ici, au format `application/problem+json`.
bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


class NotConfiguredStore:
    """Tient la place de la base sans `POSTGRES_URL` : toute utilisation lève `StoreFailed`."""

    def __getattr__(self, name: str) -> Any:
        raise StoreFailed("POSTGRES_URL n'est pas configuré")


@dataclass
class Components:
    store: AlertStore
    service: AlertService
    hub: EventHub
    reader: EventsReader | None = None
    closers: list[Callable[[], None]] = field(default_factory=list)

    def start(self) -> None:
        if self.reader is not None:
            self.reader.start()

    def close(self) -> None:
        if self.reader is not None:
            self.reader.stop()
        for close in self.closers:
            close()


def build_components(settings: Settings) -> Components:
    closers: list[Callable[[], None]] = []
    store: AlertStore
    if settings.dsn:
        pg = PostgresAlertStore(
            settings.dsn, max_size=settings.postgres_pool_max, timeout_s=settings.postgres_timeout_s
        )
        closers.append(pg.close)
        store = pg
    else:
        store = NotConfiguredStore()  # type: ignore[assignment]
    hub = EventHub(settings.sse_queue_size)
    reader = None
    if settings.sse_enabled and settings.kafka_bootstrap_servers:
        reader = EventsReader(settings.kafka_bootstrap_servers, TOPIC_ALERTS, hub.on_bus_message)
    return Components(store, AlertService(store), hub, reader, closers)


_components: Components | None = None
_lock = threading.Lock()


def get_components() -> Components:
    # Une seule instance par processus, créée à la demande.
    global _components  # noqa: PLW0603
    if _components is None:
        with _lock:
            if _components is None:
                _components = build_components(get_settings())
    return _components


def close_components() -> None:
    global _components  # noqa: PLW0603
    with _lock:
        components, _components = _components, None
    if components is not None:
        components.close()


def get_store() -> AlertStore:
    return get_components().store


def get_service() -> AlertService:
    return get_components().service


def get_hub() -> EventHub:
    return get_components().hub


# ------------------------------------------------------------------------------- authentification
def unauthenticated() -> ProblemError:
    return ProblemError(
        UNAUTHENTICATED,
        "Jeton absent, invalide ou expiré.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> Claims:
    if credentials is None:
        raise unauthenticated()
    if settings.jwt_secret is None:
        raise ProblemError(
            UPSTREAM_UNAVAILABLE, "L'authentification n'est pas configurée sur ce service."
        )
    try:
        return decode_token(credentials.credentials, secret=settings.jwt_secret.get_secret_value())
    except InvalidToken as error:
        raise unauthenticated() from error


def require_role(minimum: Role) -> Callable[..., Claims]:
    """401 sans jeton valide, 403 si le rôle est insuffisant. Même contrat que l'API métier."""

    def dependency(claims: Claims = Depends(current_claims)) -> Claims:
        if not has_at_least(claims.role, minimum):
            raise ProblemError(
                FORBIDDEN,
                f"Le rôle `{claims.role.value}` ne permet pas cette opération ; "
                f"rôle requis `{minimum.value}`.",
            )
        return claims

    return dependency
