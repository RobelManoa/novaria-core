"""Scénarios : l'état de congestion VOULU de chaque tronçon à chaque instant (vérité terrain) et la demande.

L'état est défini par le scénario, indépendamment de la règle de seuils (ADR-027, section 3.3) : le simulateur en tire
ensuite des mesures bruitées. Les heures sont des heures du jour en UTC (réseau fictif, pas de fuseau local).
La graine ne change pas le calendrier des états : elle ne fait varier que le bruit des mesures.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache

from . import rng
from .network import SEGMENT_BY_ID, SEGMENTS, Segment

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

    def demand_at(self, segment: Segment, instant: datetime) -> float:
        """Part de la capacité demandée à cet instant : de quoi tirer le nombre de véhicules (même formule qu'avant la campagne)."""
        return self.demand_scale * demand_factor(segment.road_type, int(instant.timestamp()) % 86400)


# --- Campagne : des jours différents les uns des autres (IA-12) ---------------------------------------------------------
# Les trois scénarios ci-dessus rejouent le MÊME calendrier de congestion (la graine ne change que le bruit) : un modèle y voit
# trois situations, pas plus. La campagne fait varier le calendrier lui-même, jour par jour : jour de semaine ou de week-end,
# pluie, pointes décalées, incidents à des heures et des endroits tirés au hasard. Le calendrier d'un jour ne dépend QUE de sa
# date (graine fixe ci-dessous) : deux runs du même jour ont le même calendrier, comme pour les autres scénarios, et la graine
# d'un run ne change toujours que le bruit des mesures. L'état voulu vient de la charge du tronçon, pas de la règle de seuils.

CAMPAIGN_ID = "campagne"
CAMPAIGN_SEED = 2026  # fixe le calendrier de la campagne ; ne pas confondre avec la graine d'un run
SLOW_LOAD, CONGESTED_LOAD = 0.60, 0.90  # charge (part de la capacité d'une artère à sa pointe) à partir de laquelle l'état change
# Demande d'un jour de week-end : pas de pointe nette, un plateau de fin de matinée à l'après-midi.
_WEEKEND_DEMAND = (
    0.10, 0.07, 0.05, 0.05, 0.06, 0.10, 0.18, 0.30, 0.45, 0.58, 0.68, 0.74, 0.76,
    0.74, 0.72, 0.70, 0.66, 0.60, 0.50, 0.40, 0.30, 0.22, 0.16, 0.12, 0.10,
)


@dataclass(frozen=True)
class Incident:
    road_segment_id: str
    start_s: int  # secondes depuis minuit UTC du jour
    duration_s: int


@dataclass(frozen=True)
class DayPlan:
    """Le calendrier voulu d'un jour de la campagne : ce qui le distingue des autres jours."""

    day: date
    kind: str  # « semaine » ou « weekend »
    weather: str  # « sec » ou « pluie »
    scale: float  # multiplie la demande du jour
    shift_s: int  # décalage des pointes (secondes, négatif : plus tôt)
    incidents: tuple[Incident, ...]


def _interpolate(table: tuple[float, ...], seconds: float) -> float:
    position = seconds / 3600
    low = min(max(int(position), 0), 23)
    share = min(max(position - low, 0.0), 1.0)
    return table[low] * (1 - share) + table[low + 1] * share


@lru_cache(maxsize=1024)
def day_plan(day: date) -> DayPlan:
    """Calendrier d'un jour, fonction pure de la date (BLAKE2b : identique sur toute machine et toute version de Python)."""
    iso = day.isoformat()

    def u(*key: object) -> float:
        return rng.uniform(CAMPAIGN_SEED, "jour", iso, *key)

    weekday = day.weekday() < 5
    rainy = u("pluie") < 0.25
    scale = (0.85 + 0.30 * u("echelle")) if weekday else (0.55 + 0.25 * u("echelle"))
    scale *= 1.10 if rainy else 1.0
    shift = int((u("decalage") - 0.5) * 2 * 20 * 60) if weekday else 0
    draw = u("incidents")
    count = (0 if draw < 0.40 else 1 if draw < 0.85 else 2) if weekday else (0 if draw < 0.70 else 1)
    incidents = []
    for i in range(count):
        segment = SEGMENTS[int(u("incident", i, "tronçon") * len(SEGMENTS))]
        start = 6 * 3600 + int(u("incident", i, "début") * 14 * 12) * 300  # tous les 5 minutes, de 06:00 à 20:00
        duration = (3 + int(u("incident", i, "durée") * 10)) * 300  # de 15 à 60 minutes
        incidents.append(Incident(segment.road_segment_id, start, duration))
    return DayPlan(day, "semaine" if weekday else "weekend", "pluie" if rainy else "sec", round(scale, 4), shift, tuple(incidents))


def _tidal(plan: DayPlan, segment: Segment, seconds: int) -> float:
    """Le matin Nord et Ouest sont chargés, le soir Est et Sud (un jour de semaine seulement)."""
    if plan.kind != "semaine":
        return 1.0
    hour = seconds / 3600
    if 6 <= hour < 10:
        return 1.15 if segment.approach in ("N", "W") else 0.85
    if 16 <= hour < 20:
        return 1.15 if segment.approach in ("E", "S") else 0.85
    return 1.0


def _load(plan: DayPlan, segment: Segment, seconds: int) -> float:
    table = _HOURLY_DEMAND if plan.kind == "semaine" else _WEEKEND_DEMAND
    profile = _interpolate(table, (seconds - plan.shift_s) % 86400)
    wobble = 0.92 + 0.16 * rng.uniform(CAMPAIGN_SEED, "tronçon", plan.day.isoformat(), segment.road_segment_id)
    return plan.scale * profile * _ROAD_TYPE_SCALE[segment.road_type] * _tidal(plan, segment, seconds) * wobble


def _rank(state: str) -> int:
    return (FREE_FLOW, SLOW, CONGESTED).index(state)


class CampaignScenario(Scenario):
    """Plusieurs jours aux calendriers différents ; le début et la durée se règlent à la ligne de commande (`--start`, `--duration`)."""

    def label_state(self, segment: Segment, instant: datetime) -> str:
        instant = instant.astimezone(UTC)
        plan = day_plan(instant.date())
        seconds = instant.hour * 3600 + instant.minute * 60 + instant.second
        load = _load(plan, segment, seconds)
        state = CONGESTED if load >= CONGESTED_LOAD else SLOW if load >= SLOW_LOAD else FREE_FLOW
        for incident in plan.incidents:
            end = incident.start_s + incident.duration_s
            if segment.road_segment_id == incident.road_segment_id:
                if incident.start_s <= seconds < end:
                    candidate = CONGESTED
                elif end <= seconds < end + 15 * 60:
                    candidate = SLOW  # il se résorbe
                else:
                    continue
            elif segment.intersection_id == SEGMENT_BY_ID[incident.road_segment_id].intersection_id and incident.start_s + 300 <= seconds < end:
                candidate = SLOW  # les autres approches du carrefour ralentissent
            else:
                continue
            if _rank(candidate) > _rank(state):
                state = candidate
        return state

    def demand_at(self, segment: Segment, instant: datetime) -> float:
        instant = instant.astimezone(UTC)
        seconds = instant.hour * 3600 + instant.minute * 60 + instant.second
        return _load(day_plan(instant.date()), segment, seconds)


SCENARIOS = {
    scenario.scenario_id: scenario
    for scenario in (
        Scenario("journee-calme", "Une journée entière sans congestion : tous les tronçons restent fluides.", "00:00", 24 * 3600, 0.6, _calm),
        Scenario("heure-de-pointe", "Pointe du matin : les approches Nord et Ouest se saturent entre 07:20 et 08:50, avec un décalage par tronçon.", "06:00", 5 * 3600, 1.0, _morning_peak),
        Scenario("incident-ponctuel", "Incident sur ROAD_005 de 08:10 à 08:35 ; les autres approches du carrefour INT_02 ralentissent.", "07:30", 3 * 3600, 0.8, _incident),
        CampaignScenario(CAMPAIGN_ID, "Campagne : un calendrier différent par jour (semaine, week-end, pluie, pointes décalées, incidents tirés au sort) ; régler --start et --duration.", "00:00", 24 * 3600, 1.0, _calm),
    )
}
