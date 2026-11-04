"""Réseau fixe de la migration 0005 : 6 carrefours, 24 tronçons d'approche, 24 capteurs.

Même table que `scripts/dev/gen_reseau.py`, qui génère la migration `db/postgres/migrations/0005_reseau_demo.sql` :
un test compare les deux, donc toute dérive est détectée. La vitesse en circulation fluide est la vitesse limite.
"""

from dataclasses import dataclass

INTERVAL_S = 10  # une mesure toutes les 10 s par capteur (dim_sensor.reporting_interval_s)

# (identifiant, type de route, voies, longueur d'approche en m, vitesse limite km/h)
INTERSECTIONS = (
    ("INT_01", "ARTERIAL", 2, 300, 50),
    ("INT_02", "ARTERIAL", 2, 300, 50),
    ("INT_03", "COLLECTOR", 1, 250, 50),
    ("INT_04", "COLLECTOR", 1, 250, 50),
    ("INT_05", "LOCAL", 1, 150, 30),
    ("INT_06", "LOCAL", 1, 150, 30),
)
APPROACHES = ("N", "E", "S", "W")


@dataclass(frozen=True)
class Segment:
    """Un tronçon d'approche et son capteur (un capteur par tronçon)."""

    road_segment_id: str
    intersection_id: str
    approach: str
    road_type: str
    lane_count: int
    length_m: int
    speed_limit_kmh: int
    sensor_id: str

    @property
    def free_flow_speed_kmh(self) -> int:
        return self.speed_limit_kmh


def _build() -> tuple[Segment, ...]:
    segments = []
    number = 0
    for intersection_id, road_type, lanes, length, limit in INTERSECTIONS:
        for approach in APPROACHES:
            number += 1
            segments.append(
                Segment(
                    road_segment_id=f"ROAD_{number:03d}",
                    intersection_id=intersection_id,
                    approach=approach,
                    road_type=road_type,
                    lane_count=lanes,
                    length_m=length,
                    speed_limit_kmh=limit,
                    sensor_id=f"SENSOR_{number:03d}",
                )
            )
    return tuple(segments)


SEGMENTS = _build()
SEGMENT_BY_SENSOR = {segment.sensor_id: segment for segment in SEGMENTS}
SEGMENT_BY_ID = {segment.road_segment_id: segment for segment in SEGMENTS}
SENSOR_IDS = tuple(segment.sensor_id for segment in SEGMENTS)
