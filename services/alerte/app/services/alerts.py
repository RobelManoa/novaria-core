"""Cycle de vie d'une alerte : créée, notifiée, acquittée, résolue (RG-16 à RG-19, ADR-028).

Chaque changement d'état s'écrit **dans une seule transaction** : la ligne de l'alerte, une ligne
d'historique et l'événement à publier (boîte d'envoi, ADR-009). Si l'une des trois écritures échoue,
aucune n'a eu lieu : un événement n'existe jamais sans changement, ni un changement sans événement.

Ce que la base ne contrôle pas et que ce module garantit : l'ordre des transitions
(CREATED -> NOTIFIED -> ACKNOWLEDGED -> RESOLVED, sans retour en arrière) et la présence de
`notified_at` à l'état NOTIFIED.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.core.config import TOPIC_ALERTS
from app.domain.model import Alert, HistoryEntry, Open, Resolve, State
from app.services.events import build_event, event_id
from app.services.ports import AlertStore, InvalidTransition, NotFound, Tx

logger = logging.getLogger("app.alerts")

SYSTEM = "system"
Clock = Callable[[], datetime]

# Position dans le cycle de vie : on ne va que vers une position plus grande.
ORDER = {State.CREATED: 0, State.NOTIFIED: 1, State.ACKNOWLEDGED: 2, State.RESOLVED: 3}


def utcnow() -> datetime:
    return datetime.now(UTC)


class OpenOutcome(StrEnum):
    CREATED = "CREATED"
    EXISTS = "EXISTS"  # une alerte non résolue existe déjà : c'est « une alerte par épisode »
    SUPPRESSED = "SUPPRESSED"  # `min_gap_s` pas encore écoulé depuis la dernière alerte


def check_transition(current: State, target: State) -> None:
    """Lève `InvalidTransition` sauf si `target` est plus loin dans le cycle que `current`."""
    if ORDER[target] <= ORDER[current]:
        raise InvalidTransition(current, target)


class AlertService:
    def __init__(
        self, store: AlertStore, *, clock: Clock = utcnow, new_id: Callable[[], str] | None = None
    ) -> None:
        self._store = store
        self._clock = clock
        self._new_id = new_id or (lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------------ écriture commune
    @staticmethod
    def _record(
        tx: Tx,
        alert: Alert,
        previous: State | None,
        at: datetime,
        actor: str,
        details: dict[str, Any] | None,
    ) -> None:
        """L'historique et l'événement d'un changement, dans la transaction de l'appelant."""
        tx.add_history(alert.alert_id, HistoryEntry(previous, alert.state, at, actor, details))
        event = build_event(alert, previous, at)
        tx.add_outbox(
            TOPIC_ALERTS, alert.intersection_id, event_id(alert.alert_id, alert.state), event
        )

    def _move(
        self,
        tx: Tx,
        alert: Alert,
        target: State,
        at: datetime,
        actor: str,
        details: dict[str, Any] | None = None,
        **changes: Any,
    ) -> Alert:
        check_transition(alert.state, target)
        moved = alert.evolve(state=target, updated_at=self._clock(), **changes)
        tx.update(moved)
        self._record(tx, moved, alert.state, at, actor, details)
        return moved

    # ------------------------------------------------------------------- créer (règles)
    def open(self, decision: Open) -> OpenOutcome:
        """Crée l'alerte de la règle pour ce tronçon, sauf si elle existe ou si c'est trop tôt."""
        rule, window = decision.rule, decision.window
        with self._store.transaction() as tx:
            run_id = window.provenance.run_id
            if tx.open_alert(rule.kind, window.road_segment_id, run_id, lock=False):
                return OpenOutcome.EXISTS
            last = tx.last_alert(rule.kind, window.road_segment_id, run_id)
            if last and (window.event_time - last.opened_at).total_seconds() < rule.min_gap_s:
                fields = {"rule_id": rule.rule_id, "road_segment_id": window.road_segment_id}
                logger.info(
                    "alerte retenue par min_gap_s",
                    extra={"fields": {**fields, "counter": "suppressed"}},
                )
                return OpenOutcome.SUPPRESSED
            alert = Alert(
                alert_id=self._new_id(),
                rule_id=rule.rule_id,
                kind=rule.kind,
                road_segment_id=window.road_segment_id,
                intersection_id=window.intersection_id,
                provenance=window.provenance,
                severity=decision.severity,
                state=State.CREATED,
                opened_at=window.event_time,  # temps d'événement : comparable à l'épisode (KPI-03)
                correlation_id=window.correlation_id,
                updated_at=self._clock(),
            )
            if not tx.insert(alert):  # une autre instance a ouvert l'alerte entre-temps
                return OpenOutcome.EXISTS
            details = {
                "indicator_id": window.event_id,
                "window_start": window.window_start.isoformat(),
                **decision.facts,
            }
            self._record(tx, alert, None, window.event_time, SYSTEM, details)
        fields = {"alert_id": alert.alert_id, "rule_id": rule.rule_id, "counter": "alerts_created"}
        logger.info(
            "alerte créée", extra={"fields": {**fields, "road_segment_id": alert.road_segment_id}}
        )
        return OpenOutcome.CREATED

    # ------------------------------------------------------------ résoudre (épisode clos)
    def resolve_auto(self, decision: Resolve) -> Alert | None:
        window = decision.window
        with self._store.transaction() as tx:
            alert = tx.open_alert(
                decision.kind, window.road_segment_id, window.provenance.run_id, lock=True
            )
            if alert is None:
                return None
            # La base exige resolved_at >= opened_at.
            at = max(window.event_time, alert.opened_at)
            details = {"indicator_id": window.event_id, "reason": "retour à la normale"}
            moved = self._move(
                tx, alert, State.RESOLVED, at, SYSTEM, details, resolved_at=at, resolution="AUTO"
            )
        fields = {"alert_id": moved.alert_id, "resolution": "AUTO", "counter": "alerts_resolved"}
        logger.info("alerte résolue", extra={"fields": fields})
        return moved

    # ----------------------------------------------------------------------------- notifier
    def mark_notified(self, alert_id: str) -> Alert | None:
        """CREATED -> NOTIFIED après la remise au canal. `None` si l'alerte a déjà avancé."""
        with self._store.transaction() as tx:
            alert = tx.get(alert_id, lock=True)
            if alert is None or alert.state is not State.CREATED:
                return None
            now = self._clock()
            return self._move(tx, alert, State.NOTIFIED, now, SYSTEM, notified_at=now)

    # ------------------------------------------------------------ actions de l'opérateur
    def acknowledge(self, alert_id: str, actor: str) -> tuple[Alert, bool]:
        """Rend (alerte, changée). Répéter l'appel sur une alerte acquittée ne change rien."""
        with self._store.transaction() as tx:
            alert = tx.get(alert_id, lock=True)
            if alert is None:
                raise NotFound(alert_id)
            if alert.state is State.ACKNOWLEDGED:
                return alert, False
            now = self._clock()
            moved = self._move(
                tx, alert, State.ACKNOWLEDGED, now, actor,
                acknowledged_at=now, acknowledged_by=actor,
            )  # fmt: skip
        return moved, True

    def resolve_manual(self, alert_id: str, actor: str, comment: str | None = None) -> Alert:
        with self._store.transaction() as tx:
            alert = tx.get(alert_id, lock=True)
            if alert is None:
                raise NotFound(alert_id)
            at = max(self._clock(), alert.opened_at)
            details = {"comment": comment} if comment else None
            return self._move(
                tx, alert, State.RESOLVED, at, actor, details, resolved_at=at, resolution="MANUAL"
            )
