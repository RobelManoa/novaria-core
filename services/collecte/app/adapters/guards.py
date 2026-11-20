"""Délais, reprises et disjoncteurs autour des dépendances de la collecte (MS-16).

Deux dépendances : le bus Kafka et MongoDB. Chacune a son disjoncteur (`app/core/resilience.py`) :
après quelques échecs de suite, il s'ouvre et la collecte répond 503 **tout de suite** au lieu
d'attendre le délai de la dépendance pour chaque mesure ; un appel d'essai part périodiquement
pour savoir si elle est revenue. Les écritures MongoDB sont rejouées avec une attente croissante
(elles sont idempotentes : index unique sur l'`id`, recherche préalable) ; la publication Kafka ne
l'est pas ici, car l'émetteur renvoie déjà sur un 503 et son accusé est borné (`acks=all`).

Tout est visible : `GET /metrics` (état des disjoncteurs, appels, reprises, durées) et le journal
(`disjoncteur ouvert`, `reprise`), avec l'identifiant de corrélation de la mesure en cours.
"""

import logging

from app.core.metrics import REGISTRY, Registry
from app.core.resilience import STATE_VALUE, CircuitBreaker, CircuitOpen, retry
from app.services.ingestion import PublishFailed, StoreFailed

logger = logging.getLogger("app.resilience")

REGISTRY.describe(
    "novaria_circuit_state", "gauge", "État du disjoncteur : 0 fermé, 1 semi-ouvert, 2 ouvert"
)
REGISTRY.describe("novaria_circuit_opened_total", "counter", "Ouvertures du disjoncteur")
REGISTRY.describe("novaria_dependency_calls_total", "counter", "Appels à une dépendance, par issue")
REGISTRY.describe(
    "novaria_dependency_retries_total", "counter", "Reprises d'un appel à une dépendance"
)
REGISTRY.describe(
    "novaria_dependency_duration_seconds", "histogram", "Durée des appels à une dépendance"
)


def observer_for(registry: Registry = REGISTRY):
    """L'observateur qui transforme les événements du disjoncteur en métriques et en journal."""

    def observe(event: str, **fields) -> None:
        dependency = {"dependency": fields["name"]}
        if event == "call":
            registry.inc(
                "novaria_dependency_calls_total", {**dependency, "outcome": fields["outcome"]}
            )
            registry.observe(
                "novaria_dependency_duration_seconds", fields["duration_s"], dependency
            )
        elif event == "rejected":
            registry.inc("novaria_dependency_calls_total", {**dependency, "outcome": "rejected"})
        elif event == "retry":
            registry.inc("novaria_dependency_retries_total", dependency)
            logger.warning(
                "reprise",
                extra={"fields": {k: fields[k] for k in ("name", "attempt", "delay_s", "error")}},
            )
        elif event == "state":
            registry.set("novaria_circuit_state", STATE_VALUE[fields["after"]], dependency)
            if fields["after"] == "open":
                registry.inc("novaria_circuit_opened_total", dependency)
            message = {
                "open": "disjoncteur ouvert",
                "half_open": "disjoncteur semi-ouvert",
                "closed": "disjoncteur fermé",
            }
            logger.log(
                logging.WARNING if fields["after"] == "open" else logging.INFO,
                message[fields["after"]],
                extra={
                    "fields": {
                        "dependency": fields["name"],
                        "before": fields["before"],
                        "failures": fields["failures"],
                    }
                },
            )

    return observe


_CIRCUITS: list[tuple[Registry, CircuitBreaker]] = []


def breaker(
    name: str, *, failures: int, reset_s: float, trip_on, registry: Registry = REGISTRY, **options
) -> CircuitBreaker:
    registry.set("novaria_circuit_state", 0, {"dependency": name})
    circuit = CircuitBreaker(
        name,
        failure_threshold=failures,
        reset_timeout_s=reset_s,
        trip_on=trip_on,
        observer=observer_for(registry),
        **options,
    )
    _CIRCUITS.append((registry, circuit))
    return circuit


def refresh_circuits(registry: Registry = REGISTRY) -> None:
    """Relit l'état réel de chaque disjoncteur (à appeler à chaque lecture de /metrics).

    Un disjoncteur ouvert ne passe « semi-ouvert » qu'à l'appel suivant : sans trafic, sa jauge
    resterait à « ouvert » pour toujours. La lecture de `state` applique le délai écoulé et
    prévient l'observateur (jauge et journal).
    """
    for owner, circuit in _CIRCUITS:
        if owner is registry:
            _ = circuit.state


class GuardedPublisher:
    """Le producteur Kafka derrière son disjoncteur : ouvert, `PublishFailed` tout de suite."""

    def __init__(self, inner, circuit: CircuitBreaker) -> None:
        self._inner, self._circuit = inner, circuit

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        try:
            self._circuit.call(self._inner.publish, topic, key, value)
        except CircuitOpen as error:
            raise PublishFailed(str(error)) from error

    def close(self) -> None:
        self._inner.close()


class _Guarded:
    def __init__(
        self, circuit: CircuitBreaker, attempts: int, base_s: float, observer, sleep=None
    ) -> None:
        self._circuit, self._attempts, self._base_s, self._observer = (
            circuit,
            attempts,
            base_s,
            observer,
        )
        self._sleep = sleep

    def _run(self, function):
        def attempt():
            return retry(
                function,
                attempts=self._attempts,
                base_s=self._base_s,
                retry_on=(StoreFailed,),
                observer=self._observer,
                name=self._circuit.name,
                **({"sleep": self._sleep} if self._sleep else {}),
            )

        try:
            return self._circuit.call(attempt)
        except CircuitOpen as error:
            raise StoreFailed(str(error)) from error


class GuardedRawEvents(_Guarded):
    def __init__(self, inner, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._inner = inner

    def exists(self, event_id: str) -> bool:
        return self._run(lambda: self._inner.exists(event_id))

    def insert(self, document: dict) -> bool:
        return self._run(lambda: self._inner.insert(document))


class GuardedRejects(_Guarded):
    def __init__(self, inner, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._inner = inner

    def insert(self, document: dict) -> None:
        return self._run(lambda: self._inner.insert(document))
