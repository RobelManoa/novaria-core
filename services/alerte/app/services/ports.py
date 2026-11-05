"""Ce que le cœur du service demande au monde extérieur (ADR-010 : ports et adaptateurs).

`adapters/postgres_store.py`, `adapters/kafka_io.py` et `adapters/channels.py` en sont les versions
réelles ; les tests unitaires utilisent des faux (`tests/support.py`).
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.domain.model import Alert, HistoryEntry, Kind, Rule, State


class StoreFailed(Exception):
    """La base ne répond pas ou refuse l'écriture : rien n'a été modifié (transaction annulée)."""


class PublishFailed(Exception):
    """Le bus n'a pas accusé réception : l'appelant ne valide rien et recommence."""


class NotificationFailed(Exception):
    """Le canal de notification n'a pas pu remettre l'alerte : elle reste à l'état CREATED."""


class NotFound(Exception):
    """Aucune alerte (ou règle) de cet identifiant."""


class InvalidTransition(Exception):
    """L'alerte ne peut pas passer à cet état depuis celui où elle est."""

    def __init__(self, current: State, target: State) -> None:
        super().__init__(f"{current.value} -> {target.value}")
        self.current = current
        self.target = target


@dataclass(frozen=True)
class OutboxRow:
    outbox_id: int
    topic: str
    event_key: str
    event_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AlertFilter:
    state: State | None = None
    kind: Kind | None = None
    severity: str | None = None
    intersection_id: str | None = None
    road_segment_id: str | None = None
    opened_from: datetime | None = None
    opened_to: datetime | None = None


class Tx(Protocol):
    """Une transaction : tout ce qui s'y écrit est validé ensemble, ou rien."""

    def last_alert(self, kind: Kind, segment: str, run_id: str) -> Alert | None:
        """La plus récemment ouverte, résolue ou non."""

    def open_alert(self, kind: Kind, segment: str, run_id: str, *, lock: bool) -> Alert | None:
        """L'alerte non résolue de ce type pour ce tronçon et ce run, s'il y en a une."""

    def get(self, alert_id: str, *, lock: bool) -> Alert | None: ...

    def insert(self, alert: Alert) -> bool:
        """Faux si l'index unique des alertes non résolues refuse (une autre l'a précédée)."""

    def update(self, alert: Alert) -> None: ...

    def add_history(self, alert_id: str, entry: HistoryEntry) -> None: ...

    def add_outbox(self, topic: str, key: str, event_id: str, payload: dict[str, Any]) -> None: ...


class AlertStore(Protocol):
    def transaction(self) -> AbstractContextManager[Tx]: ...

    def rules(self) -> list[Rule]: ...

    def update_rule(
        self, rule_id: str, *, enabled: bool | None, params: dict[str, Any] | None,
        min_gap_s: int | None,
    ) -> Rule:  # fmt: skip
        """Lève `NotFound`."""

    def pending_notification(self, limit: int) -> list[Alert]: ...

    def list_alerts(
        self, filters: AlertFilter, *, after: tuple[datetime, str] | None, limit: int
    ) -> list[Alert]:  # fmt: skip
        """Par `opened_at` décroissant puis `alert_id` ; `after` = (ouverture, id) du dernier vu."""

    def get_alert(self, alert_id: str) -> tuple[Alert, list[HistoryEntry]] | None: ...

    def relay_outbox(self, publish: Callable[[OutboxRow], None], *, limit: int) -> int:
        """Publie, dans l'ordre, les lignes non publiées ; rend leur nombre.

        Une ligne n'est marquée publiée qu'une fois `publish` revenu sans erreur.
        """


class EventPublisher(Protocol):
    def publish(self, topic: str, key: str | None, value: bytes) -> None: ...

    def flush(self) -> None: ...


class NotificationChannel(Protocol):
    def send(self, alert: Alert) -> None:
        """Lève `NotificationFailed`."""
