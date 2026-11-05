"""Jeu de test du critère de MS-10 : 40 minutes de mesures sur deux carrefours de démonstration.

Déterministe (graine fixe). Il contient exprès de quoi faire diverger un calcul approximatif :

| Où | Quoi |
|---|---|
| ROAD_001, minutes 6 à 16 | ralentissement, congestion, route vide en pleine congestion (fenêtre |
| | retenue), trou de données pendant la congestion, retour au fluide |
| ROAD_002, minute 10 | 4 mesures sur 6 dont les occupations moyennent 0,3125 : égalité d'arrondi |
| ROAD_002, minute 20 | 2 mesures sur 6 : complétude insuffisante, état `UNKNOWN` |
| ROAD_003, minute 5 | mesures `PARTIAL` (vitesse absente malgré des véhicules) |
| ROAD_003, minute 15 | une mesure `SUSPECT` (190 km/h), exclue des indicateurs |
| ROAD_004, minute 25 | vitesses moyennant 38,25 : égalité d'arrondi (38,3 et non 38,2) |
| ROAD_005, minutes 10 à 22 | une autre congestion, sur l'autre carrefour |
| ROAD_006, 30 et 31 | ratio 0,606, juste au-dessus du seuil de ralentissement : fluide |
| ROAD_007, 3 et 4 | ratio 0,352, juste au-dessus du seuil de congestion : ralenti seulement |
| ROAD_008, 8 à 15 | congestion, puis ratio 0,452 (seuil 0,45), puis 0,704 (seuil 0,70) |
"""

import random
from datetime import UTC, datetime, timedelta

from tests.unit.flux.support import message

RUN = "ref-run-0001"
START = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
MINUTES = 40
SENSOR_OF = {f"ROAD_00{n}": f"SENSOR_00{n}" for n in range(1, 9)}
INTERVAL_S = 10


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_speed(segment: str, minute: int, rng: random.Random) -> float:
    free = rng.randint(400, 480) / 10
    if segment == "ROAD_001":
        if 6 <= minute <= 7:
            return 28.0
        if 8 <= minute <= 10:
            return 15.0
        if minute in (12, 13):
            return 14.0
        if 14 <= minute <= 16:
            return 42.0
    if segment == "ROAD_005":
        if 10 <= minute <= 11:
            return 27.0
        if 12 <= minute <= 15:
            return 12.0
        if 16 <= minute <= 22:
            return 41.0
    return free


def _exact_speed(segment: str, minute: int) -> float | None:
    """Vitesse constante (sans bruit) des fenêtres collées à un seuil de l'ADR-028."""
    if segment == "ROAD_006" and minute in (30, 31):
        return 30.3  # ratio 0,606
    if segment == "ROAD_007" and minute in (3, 4):
        return 17.6  # ratio 0,352
    if segment == "ROAD_008":
        if minute in (8, 9):
            return 15.0  # ratio 0,3 : congestion
        if minute in (10, 11, 12):
            return 22.6  # ratio 0,452
        if minute in (13, 14, 15):
            return 35.2  # ratio 0,704
    return None


def generate() -> list[dict]:
    """Les messages `iot.raw`, dans l'ordre où ils arrivent (par fin d'intervalle, puis capteur)."""
    rng = random.Random(20261020)  # noqa: S311 - jeu de test reproductible, pas de cryptographie
    messages = []
    for segment, sensor in SENSOR_OF.items():
        intersection = "INT_01" if segment <= "ROAD_004" else "INT_02"
        for minute in range(MINUTES):
            base = _base_speed(segment, minute, rng)
            slots = list(range(6))
            if (segment, minute) == ("ROAD_001", 12) or (segment, minute) == ("ROAD_002", 20):
                slots = [0, 1]
            if (segment, minute) == ("ROAD_002", 10):
                slots = [0, 1, 2, 3]
            for slot in slots:
                count = rng.randint(1, 9)
                speed: float | None = round(base + rng.randint(-5, 5) / 10, 1)
                if (exact := _exact_speed(segment, minute)) is not None:
                    speed = exact
                occupancy = rng.randint(5, 60) / 100
                queue = rng.randint(0, 400) / 10
                status, flags = "VALID", None
                if (segment, minute) == ("ROAD_001", 11):
                    count, speed = 0, None
                if (segment, minute) == ("ROAD_002", 10):
                    occupancy = [0.31, 0.31, 0.31, 0.32][slot]
                if (segment, minute) == ("ROAD_003", 5) and slot in (1, 4):
                    speed, status, flags = None, "PARTIAL", ["MISSING_SPEED"]
                if (segment, minute, slot) == ("ROAD_003", 15, 3):
                    count, speed, status, flags = 5, 190.0, "SUSPECT", ["IMPLAUSIBLE_VALUE"]
                if (segment, minute) == ("ROAD_004", 25):
                    count, speed = [(1, 38.2), (1, 38.3)][slot] if slot < 2 else (0, None)
                end = START + timedelta(minutes=minute, seconds=(slot + 1) * INTERVAL_S)
                document = message(
                    sensor=sensor, road=segment, time=stamp(end), count=count, speed=speed,
                    occupancy=occupancy, status=status, flags=flags, run=RUN,
                )  # fmt: skip
                document["data"]["queue_length_m"] = queue
                document["data"]["intersection_id"] = intersection
                document["subject"] = intersection
                messages.append(document)
    return sorted(messages, key=lambda m: (m["time"], m["data"]["sensor_id"]))
