"""Modèles Pydantic des événements du bus, alignés sur `contracts/events/` (MS-03, ADR-012).

Un modèle par sujet : `iot.raw`, `traffic.indicators`, `traffic.recommendations`,
`alerts.events`, `signal.status` et `errors.dlq`. Les modèles sont **stricts** (aucun champ
inconnu, aucune conversion de type) comme les schémas JSON, qui font foi. Le test
`tests/contract/test_event_models.py` échoue dès qu'un modèle et un schéma divergent.

Portée : la structure, les bornes et les règles conditionnelles du schéma. Les règles entre
champs que le schéma ne sait pas exprimer (par exemple `subject` égal à
`data.intersection_id`) sont dans `contracts/validate_events.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

UTC_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$"


def _real_date(value: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"date impossible : {value}") from error
    return value


def _uuid(value: str) -> str:
    if any(value[i : i + 1] != "-" for i in (8, 13, 18, 23)):
        raise ValueError(f"UUID mal formé : {value}")
    try:
        uuid.UUID(value)
    except ValueError as error:
        raise ValueError(f"UUID mal formé : {value}") from error
    return value


def _unique(values: list) -> list:
    if len(values) != len(set(map(str, values))):
        raise ValueError("les éléments doivent être uniques")
    return values


def _text(**constraints: Any) -> Any:
    return Annotated[str, StringConstraints(**constraints)]


UtcDateTime = Annotated[str, StringConstraints(pattern=UTC_PATTERN), AfterValidator(_real_date)]
Uuid = Annotated[str, AfterValidator(_uuid)]
IntersectionId = _text(pattern=r"^INT_[0-9]{2,}$")
EventSubject = _text(pattern=r"^(INT_[0-9]{2,}|UNKNOWN)$")
RoadSegmentId = _text(pattern=r"^ROAD_[0-9]{3,}$")
SensorId = _text(pattern=r"^SENSOR_[0-9]{3,}$")
SignalPhaseId = _text(pattern=r"^P[0-9]+$")
Approach = Literal["N", "E", "S", "W"]
CongestionState = Literal["UNKNOWN", "FREE_FLOW", "SLOW", "CONGESTED"]
UniqueApproaches = Annotated[list[Approach], Field(min_length=1), AfterValidator(_unique)]


class _Model(BaseModel):
    """Base stricte : un champ inconnu ou un type approché est refusé, comme par les schémas."""

    model_config = ConfigDict(extra="forbid", strict=True)


# Les champs facultatifs ont `= None` comme valeur par défaut : absents, ils valent None ;
# présents, ils sont validés (un `null` explicite est refusé quand le schéma ne l'autorise pas).
class Provenance(_Model):
    source_type: Literal["SIMULATED", "REAL_HISTORICAL", "REAL_LIVE"]
    run_id: _text(min_length=1, max_length=80)
    scenario_id: _text(pattern=r"^[a-z0-9_-]{1,60}$") = None
    seed: Annotated[int, Field(ge=0)] = None
    dataset_id: _text(pattern=r"^[a-z0-9_.-]{1,60}$") = None

    @model_validator(mode="after")
    def _required_by_source(self) -> Provenance:
        if self.source_type == "SIMULATED" and (self.scenario_id is None or self.seed is None):
            raise ValueError("scenario_id et seed sont obligatoires pour une donnée SIMULATED")
        if self.source_type == "REAL_HISTORICAL" and self.dataset_id is None:
            raise ValueError("dataset_id est obligatoire pour une donnée REAL_HISTORICAL")
        return self


class _Envelope(_Model):
    id: _text(min_length=1, max_length=200)
    source: _text(pattern=r"^[a-z][a-z0-9_-]*(/[A-Za-z0-9_.:-]+)*$", max_length=200)
    time: UtcDateTime
    correlation_id: _text(min_length=1, max_length=100) = None


# ----------------------------------------------------------------------------------------- iot.raw
class Quality(_Model):
    status: Literal["VALID", "PARTIAL", "SUSPECT"]
    flags: Annotated[
        list[
            Literal["MISSING_SPEED", "MISSING_OCCUPANCY", "IMPLAUSIBLE_VALUE", "LATE", "GAP_BEFORE"]
        ],
        AfterValidator(_unique),
    ] = None


class MeasurementData(_Model):
    sensor_id: SensorId
    road_segment_id: RoadSegmentId
    intersection_id: IntersectionId
    interval_s: Annotated[int, Field(ge=1, le=3600)]
    vehicle_count: Annotated[int, Field(ge=0, le=100000)]
    average_speed_kmh: Annotated[float, Field(ge=0, le=200)] | None
    occupancy_rate: Annotated[float, Field(ge=0, le=1)] | None
    queue_length_m: Annotated[float, Field(ge=0, le=10000)] = None
    quality: Quality
    provenance: Provenance

    @model_validator(mode="after")
    def _conditional_rules(self) -> MeasurementData:
        if self.vehicle_count == 0 and self.average_speed_kmh is not None:
            raise ValueError("average_speed_kmh doit être null quand aucun véhicule n'est passé")
        if self.quality.status == "VALID":
            if self.occupancy_rate is None:
                raise ValueError("occupancy_rate est obligatoire pour une mesure VALID")
            if self.vehicle_count >= 1 and self.average_speed_kmh is None:
                raise ValueError(
                    "average_speed_kmh est obligatoire pour une mesure VALID avec des véhicules"
                )
        return self


class MeasurementEvent(_Envelope):
    type: Literal["novaria.iot.measurement.v1"]
    subject: IntersectionId
    schema_version: Literal["1.0"]
    domain: Literal["iot"]
    data: MeasurementData


# ------------------------------------------------------------------------------ traffic.indicators
class IndicatorData(_Model):
    road_segment_id: RoadSegmentId
    intersection_id: IntersectionId
    window_start: UtcDateTime
    window_size_s: Literal[60, 300]
    vehicle_count: Annotated[int, Field(ge=0, le=100000)]
    flow_veh_per_min: Annotated[float, Field(ge=0, le=1000)]
    average_speed_kmh: Annotated[float, Field(ge=0, le=200)] | None
    occupancy_rate: Annotated[float, Field(ge=0, le=1)] | None = None
    max_queue_length_m: Annotated[float, Field(ge=0, le=10000)] | None = None
    speed_ratio: Annotated[float, Field(ge=0, le=9.999)] | None
    sample_count: Annotated[int, Field(ge=0, le=32767)]
    expected_sample_count: Annotated[int, Field(ge=1, le=32767)]
    congestion_state: CongestionState
    classifier_version: _text(min_length=1, max_length=40)
    provenance: Provenance

    @model_validator(mode="after")
    def _conditional_rules(self) -> IndicatorData:
        if self.average_speed_kmh is None and self.speed_ratio is not None:
            raise ValueError("speed_ratio doit être null quand average_speed_kmh est null")
        if self.vehicle_count == 0 and self.average_speed_kmh is not None:
            raise ValueError("average_speed_kmh doit être null quand aucun véhicule n'est passé")
        if self.congestion_state in ("SLOW", "CONGESTED") and self.speed_ratio is None:
            raise ValueError("speed_ratio est obligatoire pour un état SLOW ou CONGESTED")
        return self


class IndicatorEvent(_Envelope):
    type: Literal["novaria.traffic.indicator.v1"]
    subject: IntersectionId
    schema_version: Literal["1.0"]
    domain: Literal["traffic"]
    data: IndicatorData


# ------------------------------------------------------------------------ traffic.recommendations
class RecommendedPhase(_Model):
    phase_id: SignalPhaseId
    green_approaches: UniqueApproaches
    duration_s: Annotated[int, Field(ge=1, le=600)]


class RecommendationMethod(_Model):
    kind: Literal["WEBSTER_REFERENCE"]
    version: _text(min_length=1, max_length=40)


class RecommendationModel(_Model):
    name: _text(min_length=1, max_length=80)
    version: _text(min_length=1, max_length=40)
    run_id: _text(min_length=1, max_length=80) | None = None
    score: Annotated[float, Field(ge=0, le=1)]


class RecommendationInputs(_Model):
    indicator_ids: Annotated[
        list[_text(min_length=1, max_length=200)], Field(min_length=1), AfterValidator(_unique)
    ]
    window_start: UtcDateTime
    window_size_s: Literal[60, 300]
    congestion_state: CongestionState


class RecommendationData(_Model):
    recommendation_id: Uuid
    intersection_id: IntersectionId
    valid_until: UtcDateTime
    cycle_s: Annotated[int, Field(ge=2, le=1200)]
    phases: Annotated[list[RecommendedPhase], Field(min_length=2, max_length=8)]
    method: RecommendationMethod
    model: RecommendationModel | None = None
    inputs: RecommendationInputs
    provenance: Provenance


class RecommendationEvent(_Envelope):
    type: Literal["novaria.traffic.recommendation.v1"]
    subject: IntersectionId
    schema_version: Literal["1.0"]
    domain: Literal["traffic"]
    data: RecommendationData


# ------------------------------------------------------------------------------------- signal.stat
class SignalPhase(_Model):
    phase_id: SignalPhaseId
    green_approaches: UniqueApproaches
    min_duration_s: Annotated[int, Field(ge=1, le=600)]
    duration_s: Annotated[int, Field(ge=1, le=600)]


class SignalDecision(_Model):
    origin: Literal["RECOMMENDATION", "MANUAL_COMMAND", "FIXED_PLAN_FALLBACK", "STARTUP"]
    reference_id: Uuid | None
    outcome: Literal["APPLIED", "REFUSED"]
    refusal_reason: _text(pattern=r"^[A-Z][A-Z_]{2,59}$") | None

    @model_validator(mode="after")
    def _conditional_rules(self) -> SignalDecision:
        if (self.outcome == "REFUSED") != (self.refusal_reason is not None):
            raise ValueError(
                "refusal_reason est obligatoire si et seulement si la décision est REFUSED"
            )
        if (self.origin in ("RECOMMENDATION", "MANUAL_COMMAND")) != (self.reference_id is not None):
            raise ValueError(
                "reference_id est obligatoire pour RECOMMENDATION et MANUAL_COMMAND, null sinon"
            )
        return self


class SignalStatusData(_Model):
    intersection_id: IntersectionId
    mode: Literal["AUTOMATIC", "MANUAL", "DEGRADED_FIXED_PLAN"]
    current_phase_id: SignalPhaseId
    phase_started_at: UtcDateTime
    phases: Annotated[list[SignalPhase], Field(min_length=2, max_length=8)]
    decision: SignalDecision
    provenance: Provenance

    @model_validator(mode="after")
    def _conditional_rules(self) -> SignalStatusData:
        if self.decision.origin == "FIXED_PLAN_FALLBACK" and self.mode != "DEGRADED_FIXED_PLAN":
            raise ValueError("un retour au plan fixe met le mode à DEGRADED_FIXED_PLAN")
        return self


class SignalStatusEvent(_Envelope):
    type: Literal["novaria.signal.status.v1"]
    subject: IntersectionId
    schema_version: Literal["1.0"]
    domain: Literal["signal"]
    data: SignalStatusData


# ------------------------------------------------------------------------------------ alerts.events
class AlertData(_Model):
    alert_id: Uuid
    rule_id: _text(pattern=r"^[a-z0-9_.-]{3,60}$")
    kind: Literal["CONGESTION", "TRAFFIC_ANOMALY", "SENSOR_FAULT"]
    state: Literal["CREATED", "NOTIFIED", "ACKNOWLEDGED", "RESOLVED"]
    previous_state: Literal["CREATED", "NOTIFIED", "ACKNOWLEDGED", "RESOLVED"] | None
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    cause: Literal["UNKNOWN", "CONFIRMED_INCIDENT", "ROADWORKS", "SPECIAL_EVENT", "SENSOR_FAULT"]
    road_segment_id: RoadSegmentId
    intersection_id: IntersectionId
    episode_id: Uuid | None = None
    opened_at: UtcDateTime
    resolved_at: UtcDateTime | None
    resolution: Literal["AUTO", "MANUAL"] | None
    provenance: Provenance

    @model_validator(mode="after")
    def _conditional_rules(self) -> AlertData:
        resolved = self.state == "RESOLVED"
        if resolved != (self.resolved_at is not None) or resolved != (self.resolution is not None):
            raise ValueError(
                "resolved_at et resolution sont renseignés si et seulement si l'état est RESOLVED"
            )
        return self


class AlertEvent(_Envelope):
    type: Literal["novaria.alert.state_changed.v1"]
    subject: IntersectionId
    schema_version: Literal["1.0"]
    domain: Literal["alert"]
    data: AlertData


# -------------------------------------------------------------------------------------- errors.dlq
class RejectedData(_Model):
    source_topic: Literal[
        "iot.raw", "traffic.indicators", "traffic.recommendations", "alerts.events", "signal.status"
    ]
    rejected_at: UtcDateTime
    reason_code: Literal[
        "CONTRACT_VIOLATION",
        "SEMANTIC_VIOLATION",
        "UNREADABLE",
        "UNKNOWN_TYPE",
        "UNKNOWN_SENSOR",
        "LATE",
        "FUTURE_TIMESTAMP",
        "PROCESSING_FAILED",
    ]
    reason: _text(min_length=1, max_length=2000)
    attempts: Annotated[int, Field(ge=1, le=100)]
    original_key: _text(max_length=200) | None
    intersection_id: IntersectionId | None
    original_payload: Any

    @model_validator(mode="after")
    def _conditional_rules(self) -> RejectedData:
        if self.reason_code == "UNREADABLE" and not isinstance(self.original_payload, str):
            raise ValueError("un message illisible est conservé sous forme de texte")
        return self


class RejectedEvent(_Envelope):
    type: Literal["novaria.error.rejected.v1"]
    subject: EventSubject
    schema_version: Literal["1.0"]
    domain: Literal["error"]
    data: RejectedData


# ----------------------------------------------------------------------------------------- registre
EVENT_MODELS: dict[str, type[_Envelope]] = {
    "novaria.iot.measurement.v1": MeasurementEvent,
    "novaria.traffic.indicator.v1": IndicatorEvent,
    "novaria.traffic.recommendation.v1": RecommendationEvent,
    "novaria.alert.state_changed.v1": AlertEvent,
    "novaria.signal.status.v1": SignalStatusEvent,
    "novaria.error.rejected.v1": RejectedEvent,
}

AnyEvent = Annotated[
    MeasurementEvent
    | IndicatorEvent
    | RecommendationEvent
    | AlertEvent
    | SignalStatusEvent
    | RejectedEvent,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter[Any] = TypeAdapter(AnyEvent)


def parse_event(raw: dict) -> _Envelope:
    """Valide un événement lu sur le bus ; lève `ValidationError` s'il est hors contrat."""
    return _ADAPTER.validate_python(raw)
