"""Le vocabulaire du service d'alerte : fenêtres reçues, règles, alertes (MS-11).

Aucun import de Kafka, de PostgreSQL ni de HTTP : ce module et `rules.py` se testent seuls.
Les instants sont des `datetime` en UTC avec fuseau ; les chaînes du contrat ne passent que par
`parse_utc` et `utc_stamp`.
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

WINDOW_S = (
    60  # les règles lisent les fenêtres d'une minute ; celles de 5 minutes ne font que les résumer
)


class State(StrEnum):
    """Cycle de vie d'une alerte (ADR-028) : dans cet ordre, jamais rejoué ni reculé."""

    CREATED = "CREATED"
    NOTIFIED = "NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class Kind(StrEnum):
    CONGESTION = "CONGESTION"
    TRAFFIC_ANOMALY = "TRAFFIC_ANOMALY"
    SENSOR_FAULT = "SENSOR_FAULT"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


def parse_utc(value: str) -> datetime:
    """`2026-10-20T08:21:00Z` (ou avec fraction de seconde) vers un `datetime` UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def utc_stamp(moment: datetime) -> str:
    """Forme du contrat : UTC, fuseau explicite `Z`, microsecondes seulement si elles existent."""
    moment = moment.astimezone(UTC)
    text = moment.strftime("%Y-%m-%dT%H:%M:%S")
    if moment.microsecond:
        text += f".{moment.microsecond:06d}".rstrip("0")
    return text + "Z"


@dataclass(frozen=True)
class Provenance:
    """Origine de la donnée (ADR-027) : recopiée de l'indicateur, jamais devinée."""

    source_type: str
    run_id: str
    scenario_id: str | None = None
    seed: int | None = None
    dataset_id: str | None = None

    def as_event(self) -> dict[str, Any]:
        data: dict[str, Any] = {"source_type": self.source_type, "run_id": self.run_id}
        for name in ("scenario_id", "seed", "dataset_id"):
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        return data


@dataclass(frozen=True)
class Window:
    """Ce que les règles lisent d'un indicateur `novaria.traffic.indicator.v1`."""

    event_id: str
    event_time: datetime  # `time` de l'enveloppe : la fin de la fenêtre, temps d'événement
    correlation_id: str | None
    intersection_id: str
    road_segment_id: str
    window_start: datetime
    window_size_s: int
    congestion_state: str  # UNKNOWN, FREE_FLOW, SLOW, CONGESTED
    sample_count: int
    speed_ratio: float | None
    occupancy_rate: float | None
    max_queue_length_m: float | None
    provenance: Provenance


@dataclass(frozen=True)
class Rule:
    """Une ligne de `alertes.alert_rule`."""

    rule_id: str
    kind: Kind
    enabled: bool
    params: dict[str, Any]
    min_gap_s: int
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Open:
    """Décision : une alerte de cette règle doit exister pour ce tronçon."""

    rule: Rule
    severity: Severity
    window: Window
    facts: dict[str, Any] = field(
        default_factory=dict
    )  # valeurs observées, conservées dans l'historique


@dataclass(frozen=True)
class Resolve:
    """Décision : l'alerte ouverte de ce type pour ce tronçon, s'il y en a une, est terminée."""

    kind: Kind
    window: Window


@dataclass(frozen=True)
class Alert:
    """Une ligne de `alertes.alert`."""

    alert_id: str
    rule_id: str
    kind: Kind
    road_segment_id: str
    intersection_id: str
    provenance: Provenance
    severity: Severity
    state: State
    opened_at: datetime
    cause: str = "UNKNOWN"  # une baisse de vitesse ne prouve pas un accident (ADR-028, RG-18)
    episode_id: str | None = None
    notified_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None
    correlation_id: str | None = None
    updated_at: datetime | None = None

    def evolve(self, **changes: Any) -> "Alert":
        return replace(self, **changes)


@dataclass(frozen=True)
class HistoryEntry:
    from_state: State | None
    to_state: State
    changed_at: datetime
    actor: str
    details: dict[str, Any] | None = None
