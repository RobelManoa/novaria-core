"""Composants du service (contrôleurs, journal, bus, fils) et dépendances d'authentification.

Les composants sont créés à la demande, une fois par processus. Sans `MONGO_URL`, le journal est
indisponible : les commandes manuelles répondent 503 (on n'agit pas sans trace), les feux tournent.
Sans `KAFKA_BOOTSTRAP_SERVERS`, rien n'est lu ni publié et les feux restent au plan fixe. Les tests
remplacent ces dépendances par des faux (`app.dependency_overrides`).
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.adapters.kafka_io import KafkaPublisher, KafkaSource
from app.adapters.mongo_audit import MongoAuditLog
from app.core.auth import Claims, InvalidToken, Role, decode_token, has_at_least
from app.core.config import TOPIC_RECOMMENDATIONS, Settings, get_settings
from app.core.errors import UPSTREAM_UNAVAILABLE, ProblemError
from app.core.problems import FORBIDDEN, UNAUTHENTICATED
from app.domain.controller import SignalController
from app.domain.model import Provenance, utcnow
from app.domain.safety import DEFAULT_LAYOUT
from app.services.ingestion import RecommendationHandler
from app.services.outbox import Outbox
from app.services.ports import AuditFailed, AuditLog
from app.services.signals import SignalService
from app.worker.runtime import Dispatcher, Runtime

# `auto_error=False` : l'erreur est produite ici, au format `application/problem+json`.
bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


class NoAudit:
    """Tient la place du journal sans `MONGO_URL` : rien ne s'écrit, aucune commande ne passe."""

    def record(self, entry: dict[str, Any]) -> None:
        raise AuditFailed("MONGO_URL n'est pas configuré")

    def history(self, intersection_id: str, limit: int, cursor: str | None):
        raise AuditFailed("MONGO_URL n'est pas configuré")


class NoPublisher:
    """Tient la place du bus sans `KAFKA_BOOTSTRAP_SERVERS` : les événements sont écartés."""

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        return None

    def flush(self) -> None:
        return None


@dataclass
class Components:
    service: SignalService
    audit: AuditLog
    runtime: Runtime
    closers: list[Callable[[], None]] = field(default_factory=list)

    def start(self) -> None:
        self.runtime.start()

    def close(self) -> None:
        self.runtime.stop()
        for close in self.closers:
            close()


def build_components(settings: Settings) -> Components:
    closers: list[Callable[[], None]] = []
    audit: AuditLog = NoAudit()
    if settings.mongo_url is not None:
        mongo = MongoAuditLog(
            settings.mongo_url.get_secret_value(), timeout_ms=settings.mongo_timeout_ms
        )
        closers.append(mongo.close)
        audit = mongo
    now = utcnow()
    provenance = Provenance(
        "SIMULATED", settings.default_run_id, settings.default_scenario_id, settings.default_seed
    )
    controllers = {
        intersection_id: SignalController(
            intersection_id,
            DEFAULT_LAYOUT,
            settings.fixed_phase_s,
            now,
            provenance,
            max_silence_s=settings.max_silence_s,
        )
        for intersection_id in settings.intersections
    }
    outbox = Outbox()
    service = SignalService(
        controllers, audit, outbox, command_rate_per_min=settings.command_rate_per_min
    )
    publisher: Any = NoPublisher()
    handler = None
    source_factory = None
    if settings.kafka_bootstrap_servers:
        kafka = KafkaPublisher(
            settings.kafka_bootstrap_servers, timeout_s=settings.kafka_publish_timeout_s
        )
        closers.append(kafka.close)
        publisher = kafka
        handler = RecommendationHandler(service, outbox)

        def source_factory() -> KafkaSource:
            return KafkaSource(
                settings.kafka_bootstrap_servers, TOPIC_RECOMMENDATIONS, settings.kafka_group_id
            )

    dispatcher = Dispatcher(outbox, publisher, audit, service)
    runtime = Runtime(
        service,
        dispatcher,
        handler,
        source_factory,
        tick_interval_s=settings.tick_interval_s,
        retry_s=settings.dispatch_retry_s,
    )
    return Components(service, audit, runtime, closers)


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


def get_service() -> SignalService:
    return get_components().service


def get_audit() -> AuditLog:
    return get_components().audit


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
