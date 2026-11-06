"""Le service de réponse : contrôleurs de feux, décisions, journal et événements.

Tout l'état (un contrôleur par carrefour) est en mémoire, derrière **un seul verrou** : le fil de
lecture des recommandations, celui des phases et les requêtes de l'API ne se marchent pas dessus.
Une seule instance du service tourne (comme `alerte-worker`) : deux instances auraient deux états
de feux qui divergent.

**Ordre des garanties.**

- Une commande manuelle est **journalisée avant d'agir** : si MongoDB ne répond pas, elle n'est pas
  appliquée (`CommandNotRecorded`) et l'état est rétabli. Un opérateur ne peut pas agir sans trace.
- Un refus est toujours refusé, journal disponible ou non (au mieux, il est journalisé).
- Une décision du service (recommandation, retour au plan fixe) dépose son événement dans la file
  d'envoi **sans attendre Kafka** : les feux ne dépendent pas du bus.
"""

import copy
import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.config import TOPIC_STATUS
from app.domain.controller import SignalController, StateView
from app.domain.model import Command, Decision, Origin, Outcome, Provenance, parse_utc, utcnow
from app.domain.safety import Phase
from app.schemas.events import RecommendationEvent
from app.services.events import (
    command_entry,
    decision_entry,
    dumps,
    status_event,
)
from app.services.outbox import Outbox, Outgoing
from app.services.ports import (
    AuditFailed,
    AuditLog,
    CommandNotRecorded,
    RateLimited,
    UnknownIntersection,
)

logger = logging.getLogger("app.signals")

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class CommandResult:
    command: Command
    decision: Decision
    view: StateView
    at: datetime  # l'instant de la décision


def _provenance(data) -> Provenance:
    p = data.provenance
    return Provenance(p.source_type, p.run_id, p.scenario_id, p.seed, p.dataset_id)


class SignalService:
    def __init__(
        self,
        controllers: dict[str, SignalController],
        audit: AuditLog,
        outbox: Outbox,
        *,
        clock: Clock = utcnow,
        command_rate_per_min: int = 10,
    ) -> None:
        self._controllers = controllers
        self._audit = audit
        self._outbox = outbox
        self._clock = clock
        self._lock = threading.RLock()
        self.audit_lost = 0  # entrées d'audit qui n'ont pas pu être écrites (hors commandes)
        self._rate = command_rate_per_min
        self._recent: dict[str, deque[datetime]] = {}

    @property
    def intersections(self) -> list[str]:
        return sorted(self._controllers)

    def knows(self, intersection_id: str) -> bool:
        return intersection_id in self._controllers

    # ------------------------------------------------------------------ événements
    def _emit(
        self,
        controller: SignalController,
        decision: Decision,
        at: datetime,
        *,
        kind: str,
        correlation_id: str | None = None,
        audit: bool = True,
    ) -> None:
        view = controller.view(at)
        event = status_event(view, decision, at, kind=kind, correlation_id=correlation_id)
        entry = None
        if audit:
            entry = decision_entry(
                view, decision, at, event_id_=event["id"], correlation_id=correlation_id
            )
        self._outbox.put(
            Outgoing(TOPIC_STATUS, view.intersection_id, dumps(event), event["id"], entry)
        )

    def _step(self, controller: SignalController, now: datetime) -> None:
        """Le temps a passé : fin d'une commande tenue, recommandation périmée."""
        for decision in controller.tick(now):
            kind = "hold-ended" if decision.origin is Origin.MANUAL_COMMAND else "fallback"
            self._emit(controller, decision, now, kind=kind)

    # ------------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        """Annonce l'état de chaque carrefour au démarrage (plan fixe)."""
        with self._lock:
            now = self._clock()
            for controller in self._controllers.values():
                self._emit(controller, controller.last_decision, now, kind="startup")

    def tick(self) -> None:
        with self._lock:
            now = self._clock()
            for controller in self._controllers.values():
                self._step(controller, now)

    def stop(self) -> None:
        """Arrêt volontaire : tous les carrefours reviennent au plan fixe, et le disent."""
        with self._lock:
            now = self._clock()
            for controller in self._controllers.values():
                self._step(controller, now)
                decision = controller.stop(now)
                if decision is not None:
                    self._emit(controller, decision, now, kind="shutdown")

    # ------------------------------------------------------------------ lecture
    def view(self, intersection_id: str) -> StateView:
        with self._lock:
            controller = self._controller(intersection_id)
            now = self._clock()
            self._step(controller, now)
            return controller.view(now)

    def views(self) -> list[StateView]:
        with self._lock:
            now = self._clock()
            result = []
            for intersection_id in self.intersections:
                controller = self._controllers[intersection_id]
                self._step(controller, now)
                result.append(controller.view(now))
            return result

    def _controller(self, intersection_id: str) -> SignalController:
        try:
            return self._controllers[intersection_id]
        except KeyError:
            raise UnknownIntersection(intersection_id) from None

    # ------------------------------------------------------------------ une recommandation
    def on_recommendation(self, event: RecommendationEvent) -> str:
        """`APPLIED`, `REFUSED` ou `IGNORED` (rejouée, plus ancienne, périmée)."""
        data = event.data
        phases = [Phase(p.phase_id, tuple(p.green_approaches), p.duration_s) for p in data.phases]
        validity_s = (parse_utc(data.valid_until) - parse_utc(event.time)).total_seconds()
        with self._lock:
            controller = self._controller(data.intersection_id)
            now = self._clock()
            self._step(controller, now)
            decision = controller.on_recommendation(
                data.recommendation_id,
                parse_utc(event.time),
                phases,
                data.cycle_s,
                validity_s,
                _provenance(data),
                now,
            )
            if decision is None:
                return "IGNORED"
            self._emit(
                controller,
                decision,
                now,
                kind="recommendation",
                correlation_id=event.correlation_id,
            )
            if decision.refused:
                logger.warning(
                    "recommandation refusée par les garde-fous",
                    extra={
                        "fields": {
                            "intersection_id": data.intersection_id,
                            "recommendation_id": data.recommendation_id,
                            "refusal_reason": decision.refusal_reason,
                            "counter": "recommendations_refused",
                        }
                    },
                )
            return decision.outcome.value

    # ------------------------------------------------------------------ une commande manuelle
    def _check_rate(
        self,
        controller: SignalController,
        command: Command,
        now: datetime,
        role: str,
        correlation_id: str | None,
    ) -> None:
        """Au plus `command_rate_per_min` commandes par opérateur sur la dernière minute."""
        recent = self._recent.setdefault(command.actor, deque())
        while recent and (now - recent[0]).total_seconds() >= 60:
            recent.popleft()
        if len(recent) >= self._rate:
            retry = max(1, 60 - int((now - recent[0]).total_seconds()))
            decision = Decision(
                Origin.MANUAL_COMMAND,
                command.command_id,
                Outcome.REFUSED,
                refusal_reason="RATE_LIMITED",
                detail=f"plus de {self._rate} commandes par minute pour cet opérateur",
                reasons=("RATE_LIMITED",),
                changed=False,
            )
            view = controller.view(now)
            entry = command_entry(
                command, decision, view, now, role=role, correlation_id=correlation_id
            )
            self._journal_refusal(entry)
            raise RateLimited(retry)
        recent.append(now)

    def _journal_refusal(self, entry: dict[str, Any]) -> None:
        try:
            self._audit.record(entry)
        except AuditFailed:
            self.audit_lost += 1

    def command(
        self,
        intersection_id: str,
        command: Command,
        *,
        role: str,
        correlation_id: str | None = None,
    ) -> CommandResult:
        with self._lock:
            controller = self._controller(intersection_id)
            now = self._clock()
            self._step(controller, now)
            self._check_rate(controller, command, now, role, correlation_id)
            backup = copy.deepcopy(controller)
            decision = controller.on_command(command, now)
            view = controller.view(now)
            entry = command_entry(
                command, decision, view, now, role=role, correlation_id=correlation_id
            )
            try:
                self._audit.record(entry)
            except AuditFailed:
                if decision.changed:
                    self._controllers[intersection_id] = backup  # rien n'a eu lieu
                    logger.error(
                        "commande non appliquée : journal d'audit indisponible",
                        extra={"fields": {"intersection_id": intersection_id}},
                    )
                    raise CommandNotRecorded(intersection_id) from None
                self.audit_lost += 1
                logger.error(
                    "refus de commande non journalisé",
                    extra={
                        "fields": {
                            "intersection_id": intersection_id,
                            "counter": "audit_lost",
                        }
                    },
                )
            if decision.changed or decision.outcome is Outcome.REFUSED:
                self._emit(
                    controller,
                    decision,
                    now,
                    kind="command",
                    correlation_id=correlation_id,
                    audit=False,  # déjà journalisée, avant d'agir
                )
            return CommandResult(command, decision, view, now)

    def snapshot_state(self) -> dict[str, Any]:
        """Pour la sonde et les tests : combien d'événements attendent, d'entrées perdues."""
        return {"pending_events": len(self._outbox), "audit_lost": self.audit_lost}
