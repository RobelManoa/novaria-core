"""Journal d'audit et compteurs d'usage de l'API (BE-05) : quoi écrire, pas comment le transporter.

Un appel produit au plus une entrée d'audit (`audit_logs`) et un incrément de compteur
(`usage_stats`).

**Ce qui est écrit, et rien d'autre** (liste fermée, `build_audit_entry`) : `ts`, `service`,
`actor`, `action`, `outcome`, `correlation_id`, et dans `details` le code HTTP, la durée, le rôle de
l'appelant et les paramètres de chemin qui sont des UUID. Jamais : le corps de la requête, les
en-têtes (donc le jeton), la chaîne de requête, le nom d'utilisateur, l'adresse IP, le navigateur.
`actor` est l'identifiant (UUID) du compte, ou `anonymous` pour une connexion refusée.

Qui est audité : tout appel dont l'appelant est identifié par un jeton valide (accepté, refusé pour
rôle insuffisant, en erreur), et toute tentative de connexion. Un appel sans jeton valide n'est que
compté : il ne peut pas remplir le journal. La sonde de santé n'est ni auditée ni comptée (Docker
l'appelle toutes les 15 secondes). Le compteur utilise le **modèle** de la route
(`GET /api/v1/users/{user_id}`), jamais le chemin reçu : ni identifiant dans les clés, ni clé
choisie par l'appelant.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

ANONYMOUS = "anonymous"
UNMATCHED = "UNMATCHED"
HEALTH_PATH = "/api/v1/health"
LOGIN_PATH = "/api/v1/auth/login"
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RETRY_AFTER_FAILURE_S = 10.0


@dataclass(frozen=True)
class RequestEvent:
    """Ce que le middleware sait d'un appel terminé : rien ne vient du corps ni des en-têtes."""

    method: str
    template: str  # modèle de route, ou UNMATCHED
    status: int
    started_at: datetime
    duration_ms: float
    correlation_id: str
    actor: str | None = None  # identifiant du compte, si un jeton valide a été présenté
    role: str | None = None
    path_params: dict[str, str] = field(default_factory=dict)

    @property
    def endpoint(self) -> str:
        return f"{self.method} {self.template}"

    @property
    def audited(self) -> bool:
        return self.actor is not None or self.endpoint == f"POST {LOGIN_PATH}"


class Observer(Protocol):
    def observe(self, event: RequestEvent) -> None: ...


def outcome_of(status: int) -> str:
    """`ok` sous 400 ; `denied` pour 401 et 403 ; `error` pour toute autre erreur."""
    if status < 400:
        return "ok"
    return "denied" if status in (401, 403) else "error"


def bucket_start(moment: datetime) -> datetime:
    """Début de la tranche d'une heure UTC (tranche de `usage_stats`) qui contient `moment`."""
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def uuid_params(params: dict[str, str]) -> dict[str, str]:
    """Garde les paramètres de chemin qui sont des UUID.

    Les autres ne sont pas écrits : une valeur inconnue pourrait être un jeton collé par erreur
    dans l'adresse.
    """
    return {name: value for name, value in params.items() if UUID_PATTERN.fullmatch(str(value))}


def build_audit_entry(event: RequestEvent, service: str) -> dict:
    details: dict = {"status": event.status, "duration_ms": round(event.duration_ms, 1)}
    if event.role:
        details["role"] = event.role
    params = uuid_params(event.path_params)
    if params:
        details["path_params"] = params
    entry = {
        "ts": event.started_at.astimezone(UTC),
        "service": service,
        "actor": event.actor or ANONYMOUS,
        "action": event.endpoint,
        "outcome": outcome_of(event.status),
        "details": details,
    }
    if event.correlation_id and event.correlation_id != "-":
        entry["correlation_id"] = event.correlation_id
    return entry


class AuditRepository(Protocol):
    def insert(self, entry: dict) -> None: ...


class UsageRepository(Protocol):
    def increment(self, endpoint: str, bucket: datetime) -> None: ...


class RecordingObserver:
    """Écrit l'entrée d'audit puis le compteur ; une panne ne touche jamais la réponse du client.

    Après un échec d'écriture, les écritures suivantes sont sautées quelques secondes : une base
    éteinte ne ralentit pas chaque appel. Les événements perdus sont comptés dans `dropped` et
    journalisés.
    """

    def __init__(
        self,
        audit: AuditRepository,
        usage: UsageRepository,
        *,
        service: str,
        log,
        monotonic=time.monotonic,
    ) -> None:
        self._audit, self._usage, self._service, self._log = audit, usage, service, log
        self._monotonic = monotonic
        self._paused_until = 0.0
        self.dropped = 0

    def observe(self, event: RequestEvent) -> None:
        if self._monotonic() < self._paused_until:
            self.dropped += 1
            return
        try:
            if event.audited:
                self._audit.insert(build_audit_entry(event, self._service))
            self._usage.increment(event.endpoint, bucket_start(event.started_at))
        except Exception as error:
            # Volontairement large : une panne du journal ne doit jamais casser l'API.
            self.dropped += 1
            self._paused_until = self._monotonic() + RETRY_AFTER_FAILURE_S
            fields = {"error": type(error).__name__, "endpoint": event.endpoint}
            self._log("écriture du journal d'audit impossible", fields | {"dropped": self.dropped})
