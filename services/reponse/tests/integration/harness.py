"""Le service de réponse réel (vrais adaptateurs Kafka et MongoDB), dans le processus d'essai.

L'horloge est **accélérée** (`speed`) : les phases de 10 s minimum et les silences de 180 s se
jouent en fractions de seconde, sans toucher à une règle. Tout le reste est réel : les fils, le
consommateur de groupe, le producteur `acks=all`, le compte MongoDB `svc_reponse`.
"""

import secrets
import time
from datetime import UTC, datetime, timedelta

from app.adapters.kafka_io import KafkaPublisher, KafkaSource
from app.adapters.mongo_audit import MongoAuditLog
from app.domain.controller import SignalController
from app.domain.safety import DEFAULT_LAYOUT
from app.services.ingestion import RecommendationHandler
from app.services.outbox import Outbox
from app.services.signals import SignalService
from app.worker.runtime import Dispatcher, Runtime
from tests.integration import stack
from tests.support import PROVENANCE, T0, plan, raw, recommendation_event


def new_intersection() -> str:
    """Un carrefour à soi : les essais partagent les sujets, jamais leurs messages."""
    return f"INT_{secrets.randbelow(9000) + 1000}"


class WarpClock:
    def __init__(self, speed: float = 20.0) -> None:
        self.base = datetime.now(UTC)
        self.started = time.monotonic()
        self.speed = speed

    def __call__(self) -> datetime:
        return self.base + timedelta(seconds=(time.monotonic() - self.started) * self.speed)


class Service:
    """Un service de réponse complet : contrôleurs, journal MongoDB, bus Kafka, trois fils."""

    def __init__(
        self,
        intersections,
        *,
        group: str | None = None,
        speed: float = 20.0,
        max_silence_s: int = 180,
        bootstrap: str | None = None,
        mongo_url: str | None = None,
        mongo_timeout_ms: int = 5000,
        publish_timeout_s: float = 10.0,
        rate_per_min: int = 1000,
    ) -> None:
        self.intersections = list(intersections)
        self.clock = WarpClock(speed)
        self.group = group or f"reponse-it-{secrets.token_hex(4)}"
        bootstrap = bootstrap or stack.BOOTSTRAP
        self.audit = MongoAuditLog(mongo_url or stack.MONGO_URL, timeout_ms=mongo_timeout_ms)
        controllers = {
            name: SignalController(
                name,
                DEFAULT_LAYOUT,
                30,
                self.clock(),
                PROVENANCE,
                max_silence_s=max_silence_s,
            )
            for name in self.intersections
        }
        self.outbox = Outbox()
        self.service = SignalService(
            controllers,
            self.audit,
            self.outbox,
            clock=self.clock,
            command_rate_per_min=rate_per_min,
        )
        self.publisher = KafkaPublisher(bootstrap, timeout_s=publish_timeout_s)
        self.dispatcher = Dispatcher(self.outbox, self.publisher, self.audit, self.service)
        self.handler = RecommendationHandler(self.service, self.outbox, clock=self.clock)
        self.runtime = Runtime(
            self.service,
            self.dispatcher,
            self.handler,
            lambda: KafkaSource(bootstrap, "traffic.recommendations", self.group),
            tick_interval_s=0.05,
            retry_s=0.5,
            poll_ms=200,
        )
        self._stopped = False

    def start(self) -> "Service":
        self.runtime.start()
        return self

    def stop(self) -> None:
        """Arrêt volontaire : plan fixe pour tous, dit sur Kafka avant de partir."""
        if not self._stopped:
            self._stopped = True
            self.runtime.stop(final_drain_s=10)

    def close(self) -> None:
        self.stop()
        self.publisher.close()
        self.audit.close()

    # ------------------------------------------------------------------ aides d'essai
    def recommendation(self, intersection: str, phases=None, *, validity: float = 300) -> dict:
        """Une recommandation datée de maintenant (horloge accélérée du service)."""
        offset = (self.clock() - T0).total_seconds()
        return recommendation_event(
            intersection, plan() if phases is None else phases, at=offset, validity=validity
        )

    def warm_up(self, kafka) -> None:
        """Attend que le consommateur ait rejoint son groupe et lu : un message jeté le prouve."""
        probe = new_intersection()  # un carrefour sans feux dans ce service : rejeté sur errors.dlq
        stack.send(kafka, self.recommendation(probe))
        stack.wait_until(
            lambda: stack.on_subject("errors.dlq", probe),
            seconds=120,
            why=lambda: "le consommateur n'a rien lu (groupe sans partition ?)",
        )

    def statuses(self, intersection: str) -> list[dict]:
        return [r.event for r in stack.on_subject("signal.status", intersection)]


__all__ = ["Service", "WarpClock", "new_intersection", "raw"]
