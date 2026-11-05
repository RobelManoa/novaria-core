"""Du scénario à une mesure : comptage, vitesse moyenne, taux d'occupation (et file) d'un capteur sur un intervalle.

Chaque grandeur est tirée par `rng` à partir de (graine, capteur, instant) : jamais d'état partagé. Le ratio de vitesse
suit l'état VOULU par le scénario, avec un bruit assez large pour que les états voisins se chevauchent : la règle de seuils
de l'ADR-028 ne retrouve donc pas la vérité terrain à coup sûr, comme sur des mesures réelles.
"""

from dataclasses import dataclass
from datetime import datetime

from . import rng
from .network import INTERVAL_S, Segment
from .scenarios import CAPACITY_PER_LANE_VEH_H, CONGESTED, FREE_FLOW, SLOW, Scenario, demand_factor

# (moyenne, écart-type) du ratio vitesse / vitesse fluide, par état voulu
STATE_RATIO = {FREE_FLOW: (0.90, 0.07), SLOW: (0.50, 0.09), CONGESTED: (0.20, 0.07)}
# Part de la demande qui passe : un tronçon saturé écoule moins qu'on ne lui en demande
THROUGHPUT = {FREE_FLOW: 1.0, SLOW: 0.85, CONGESTED: 0.55}
MIN_RATIO, MAX_RATIO = 0.03, 1.12
DETECTOR_LENGTH_M = 6.0  # longueur d'un véhicule plus celle de la zone de détection
# Une voie ne s'écoule pas au-delà de sa saturation : 6 véhicules par intervalle de 10 s, soit 36 par minute, sous le seuil
# de 40 par minute et par voie de la règle DQ-05. Seule une anomalie « aberrante » franchit ce seuil.
MAX_PER_LANE = 6


@dataclass(frozen=True)
class Reading:
    """Ce que mesure un capteur sur un intervalle, avant toute anomalie."""

    label_state: str
    vehicle_count: int
    speed_kmh: float  # toujours défini ici ; la mesure émise le met à null s'il n'est passé aucun véhicule
    occupancy_rate: float
    queue_length_m: float


def occupancy(count: int, speed_kmh: float, lanes: int) -> float:
    """Part de l'intervalle où la zone de détection est occupée, moyennée sur les voies."""
    if count == 0:
        return 0.0
    speed_ms = max(speed_kmh / 3.6, 1.5)
    return round(min(0.98, count * DETECTOR_LENGTH_M / speed_ms / (INTERVAL_S * lanes)), 3)


def read(seed: int, scenario: Scenario, segment: Segment, instant: datetime) -> Reading:
    epoch = int(instant.timestamp())
    sensor = segment.sensor_id
    state = scenario.label_state(segment, instant)
    seconds = epoch % 86400
    demand = scenario.demand_scale * demand_factor(segment.road_type, seconds)
    expected = demand * CAPACITY_PER_LANE_VEH_H * segment.lane_count * INTERVAL_S / 3600 * THROUGHPUT[state]
    count = min(rng.poisson(rng.uniform(seed, "count", sensor, epoch), expected), MAX_PER_LANE * segment.lane_count)

    mean, deviation = STATE_RATIO[state]
    ratio = min(MAX_RATIO, max(MIN_RATIO, mean + deviation * rng.normal(seed, "speed", sensor, epoch)))
    speed = round(ratio * segment.free_flow_speed_kmh, 1)

    # File : nulle en circulation fluide (état voulu, pas le ratio bruité), sinon d'autant plus longue que la vitesse est
    # basse, bornée par la longueur d'approche.
    queue = 0.0
    if state != FREE_FLOW:
        queue = round(segment.length_m * max(0.0, 0.8 - ratio) * (0.6 + 0.4 * rng.uniform(seed, "queue", sensor, epoch)), 1)
    return Reading(state, count, speed, occupancy(count, speed, segment.lane_count), min(queue, float(segment.length_m)))
