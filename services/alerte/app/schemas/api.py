"""Corps des réponses et des requêtes de l'API d'alerte (schémas de `alerte.openapi.yaml`).

Les dates sont des chaînes UTC au format du contrat (`2026-10-20T08:21:00Z`) : elles sont écrites
par `app/api/mapping.py`, pas par Pydantic, qui ne produit pas le `Z`.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AlertStateName = Literal["CREATED", "NOTIFIED", "ACKNOWLEDGED", "RESOLVED"]


class AlertOut(BaseModel):
    """`Alert` du contrat : mêmes valeurs que l'événement `novaria.alert.state_changed.v1`."""

    alert_id: str
    rule_id: str
    kind: Literal["CONGESTION", "TRAFFIC_ANOMALY", "SENSOR_FAULT"]
    state: AlertStateName
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    cause: Literal["UNKNOWN", "CONFIRMED_INCIDENT", "ROADWORKS", "SPECIAL_EVENT", "SENSOR_FAULT"]
    road_segment_id: str
    intersection_id: str
    episode_id: str | None
    opened_at: str
    notified_at: str | None
    acknowledged_at: str | None
    acknowledged_by: str | None
    resolved_at: str | None
    resolution: Literal["AUTO", "MANUAL"] | None
    provenance: dict[str, Any]


class AlertHistoryEntryOut(BaseModel):
    from_state: AlertStateName | None
    to_state: AlertStateName
    changed_at: str
    actor: str
    comment: str | None = None


class AlertDetailOut(AlertOut):
    history: list[AlertHistoryEntryOut]


class AlertPageOut(BaseModel):
    items: list[AlertOut]
    next_cursor: str | None


class AlertRuleOut(BaseModel):
    rule_id: str
    kind: Literal["CONGESTION", "TRAFFIC_ANOMALY", "SENSOR_FAULT"]
    enabled: bool
    params: dict[str, Any]
    min_gap_s: int
    updated_at: str


class AlertRuleListOut(BaseModel):
    items: list[AlertRuleOut]


class AlertRuleUpdate(BaseModel):
    """`AlertRuleUpdate` : au moins un champ ; `params` est **fusionné** avec l'existant."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    params: dict[str, Any] | None = None
    min_gap_s: int | None = Field(default=None, ge=0)


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=500)


class ProblemItem(BaseModel):
    field: str
    message: str


class Problem(BaseModel):
    """Erreur au format RFC 9457 (`common.yaml`, schéma `Problem`)."""

    type: str
    title: str
    status: int
    code: str
    detail: str
    correlation_id: str
    errors: list[ProblemItem] | None = None
