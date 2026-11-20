"""Messages de mesure fabriqués à la main pour les tests (forme du contrat novaria.iot.measurement.v1)."""

from __future__ import annotations


def mesure(instant: str, *, identifiant: str | None = None, troncon: str = "ROAD_001", vehicules: int = 4, vitesse: float | None = 40.0,
           occupation: float | None = 0.3, file: float | None = 10.0, qualite: str = "VALID", run: str = "run-t") -> dict:
    return {
        "id": identifiant or f"{run}:SENSOR_001:{instant}",
        "source": f"simulateur/{run}",
        "type": "novaria.iot.measurement.v1",
        "time": instant,
        "subject": "INT_01",
        "schema_version": "1.0",
        "domain": "iot",
        "data": {
            "sensor_id": "SENSOR_001",
            "road_segment_id": troncon,
            "intersection_id": "INT_01",
            "interval_s": 10,
            "vehicle_count": vehicules,
            "average_speed_kmh": vitesse,
            "occupancy_rate": occupation,
            **({"queue_length_m": file} if file is not None else {}),
            "quality": {"status": qualite},
            "provenance": {"source_type": "SIMULATED", "run_id": run, "scenario_id": "essai", "seed": 1},
        },
    }
