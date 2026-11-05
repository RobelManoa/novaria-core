"""Scénarios : l'état de congestion VOULU de chaque tronçon à chaque instant (vérité terrain) et la demande.

L'état est défini par le scénario, indépendamment de la règle de seuils (ADR-027, section 3.3) : le simulateur en tire
ensuite des mesures bruitées. Les heures sont des heures du jour en UTC (réseau fictif, pas de fuseau local).
La graine ne change pas le calendrier des états : elle ne fait varier que le bruit des mesures.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .network import SEGMENT_BY_ID, Segment

FREE_FLOW, SLOW, CONGESTED = "FREE_FLOW", "SLOW", "CONGESTED"
DEFAULT_DAY = (2026, 10, 20)  # le jour des exemples du contrat (contracts/events/examples)

# Demande relative par heure du jour (0 h à 24 h, interpolée entre les points) : creux de nuit, pointes du matin et du soir.
_HOURLY_DEMAND = (
    0.10, 0.07, 0.05, 0.05, 0.08, 0.20, 0.50, 0.95, 1.00, 0.75, 0.60, 0.62, 0.70,
    0.65, 0.62, 0.70, 0.85, 1.00, 0.95, 0.70, 0.45, 0.30, 0.20, 0.14, 0.10,
)
_ROAD_TYPE_SCALE = {"ARTERIAL": 1.0, "COLLECTOR": 0.7, "LOCAL": 0.4}
CAPACITY_PER_LANE_VEH_H = 700  # débit d'une voie d'approche à la saturation


def hm(text: str) -> int:
    """« 07:20 » devient des secondes depuis minuit."""
    hours, minutes = text.split(":")
    return int(hours) * 3600 + int(minutes) * 60


def demand_factor(road_type: str, seconds_of_day: int) -> float:
    """Part de la capacité demandée à cette heure, pour ce type de route."""
    position = seconds_of_day / 3600
    low = min(int(position), 23)
    share = position - low
    hourly = _HOURLY_DEMAND[low] * (1 - share) + _HOURLY_DEMAND[low + 1] * share
    return hourly * _ROAD_TYPE_SCALE[road_type]


def _within(seconds: int, start: str, end: str, shift: int = 0) -> bool:
    return hm(start) + shift <= seconds < hm(end) + shift


def _calm(segment: Segment, seconds: int) -> str:
    return FREE_FLOW


def _morning_peak(segment: Segment, seconds: int) -> str:
    """Les approches Nord et Ouest se saturent en premier, les autres seulement se ralentissent ; décalage par tronçon."""
    shift = (int(segment.road_segment_id[-3:]) % 4) * 4 * 60  # 0, 4, 8 ou 12 minutes
    loaded = segment.approach in ("N", "W")
    if segment.road_type == "LOCAL":
        return SLOW if loaded and _within(seconds, "07:40", "08:30", shift) else FREE_FLOW
    if loaded:
        if _within(seconds, "07:20", "08:50", shift):
            return CONGESTED
        if _within(seconds, "06:50", "09:20", shift):
            return SLOW
        return FREE_FLOW
    return SLOW if _within(seconds, "07:10", "08:40", shift) else FREE_FLOW


INCIDENT_SEGMENT = "ROAD_005"


def _incident(segment: Segment, seconds: int) -> str:
    """Un incident sur ROAD_005 de 08:10 à 08:35, qui se résorbe jusqu'à 08:50 ; les trois autres approches du carrefour ralentissent."""
    if segment.road_segment_id == INCIDENT_SEGMENT:
        if _within(seconds, "08:10", "08:35"):
            return CONGESTED
        return SLOW if _within(seconds, "08:35", "08:50") else FREE_FLOW
    same_intersection = segment.intersection_id == SEGMENT_BY_ID[INCIDENT_SEGMENT].intersection_id
    return SLOW if same_intersection and _within(seconds, "08:15", "08:40") else FREE_FLOW


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    start: str  # heure de début par défaut (UTC)
    duration_s: int  # durée par défaut
    demand_scale: float  # multiplie la demande (une journée calme reste loin de la saturation)
    state_at: Callable[[Segment, int], str]

    def default_start(self) -> datetime:
        hours, minutes = self.start.split(":")
        return datetime(*DEFAULT_DAY, int(hours), int(minutes), tzinfo=UTC)

    def label_state(self, segment: Segment, instant: datetime) -> str:
        midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.state_at(segment, int((instant - midnight).total_seconds()))


SCENARIOS = {
    scenario.scenario_id: scenario
    for scenario in (
        Scenario("journee-calme", "Une journée entière sans congestion : tous les tronçons restent fluides.", "00:00", 24 * 3600, 0.6, _calm),
        Scenario("heure-de-pointe", "Pointe du matin : les approches Nord et Ouest se saturent entre 07:20 et 08:50, avec un décalage par tronçon.", "06:00", 5 * 3600, 1.0, _morning_peak),
        Scenario("incident-ponctuel", "Incident sur ROAD_005 de 08:10 à 08:35 ; les autres approches du carrefour INT_02 ralentissent.", "07:30", 3 * 3600, 0.8, _incident),
    )
}
