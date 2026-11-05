"""Un événement `novaria.iot.measurement.v1` (contrats MS-03) : enveloppe et `data`, tel que le contrat l'exige.

L'identifiant est « <run_id>:<sensor_id>:<instant en millisecondes> » et la corrélation « corr-<instant> », comme dans
`contracts/events/examples/mesure-valide.json`. L'état de congestion voulu n'apparaît jamais ici (le contrat refuse tout
champ inconnu) : il part dans le fichier de vérité terrain.
"""

import json
from datetime import datetime

from .network import INTERVAL_S, Segment

EVENT_TYPE = "novaria.iot.measurement.v1"
SCHEMA_VERSION = "1.0"


def instant_ms(instant: datetime) -> int:
    return int(instant.timestamp() * 1000)


def utc_text(instant: datetime) -> str:
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def event_id(run_id: str, sensor_id: str, instant: datetime) -> str:
    return f"{run_id}:{sensor_id}:{instant_ms(instant)}"


def quality(status: str, flags: list[str]) -> dict:
    return {"status": status, "flags": flags} if flags else {"status": status}


def build_event(
    *,
    run_id: str,
    scenario_id: str,
    seed: int,
    segment: Segment,
    instant: datetime,
    vehicle_count: int,
    speed_kmh: float | None,
    occupancy_rate: float,
    queue_length_m: float,
    quality_block: dict,
) -> dict:
    return {
        "id": event_id(run_id, segment.sensor_id, instant),
        "source": f"simulateur/{run_id}",
        "type": EVENT_TYPE,
        "time": utc_text(instant),
        "subject": segment.intersection_id,
        "schema_version": SCHEMA_VERSION,
        "correlation_id": f"corr-{instant_ms(instant)}",
        "domain": "iot",
        "data": {
            "sensor_id": segment.sensor_id,
            "road_segment_id": segment.road_segment_id,
            "intersection_id": segment.intersection_id,
            "interval_s": INTERVAL_S,
            "vehicle_count": vehicle_count,
            "average_speed_kmh": speed_kmh if vehicle_count > 0 else None,
            "occupancy_rate": occupancy_rate,
            "queue_length_m": queue_length_m,
            "quality": quality_block,
            "provenance": {"source_type": "SIMULATED", "run_id": run_id, "scenario_id": scenario_id, "seed": seed},
        },
    }


def to_line(document: dict) -> str:
    """Une ligne JSON : séparateurs compacts et ordre des clés conservé, donc le même texte à chaque fois."""
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))

