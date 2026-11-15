"""Exécutions simulées pour les tests de dérive : journée calme, pointe, léger ralentissement."""

import random
from datetime import timedelta

from tests.fakes import START, make_row

SEGMENTS = [f"ROAD_{n:03d}" for n in range(1, 6)]


def run_rows(
    run_id: str,
    *,
    speed: float,
    flow: float,
    occupancy: float,
    minutes: int = 120,
    seed: int = 1,
    day: int = 0,
):
    """`minutes` fenêtres d'une minute par tronçon, autour des moyennes données (bruit modéré).

    `day` décale l'exécution : la plus récente est celle que l'entrepôt appelle « courante ».
    """
    rng = random.Random(seed)  # noqa: S311 : données de test, aucun usage cryptographique
    rows = []
    for minute in range(minutes):
        for segment in SEGMENTS:
            rows.append(
                make_row(
                    run_id=run_id,
                    road_segment_id=segment,
                    window_start=START + timedelta(days=day, minutes=minute),
                    speed_ratio=round(max(0.01, rng.gauss(speed, 0.06)), 3),
                    flow_veh_per_min=round(max(0.0, rng.gauss(flow, 2.0)), 2),
                    occupancy_rate=round(min(1.0, max(0.0, rng.gauss(occupancy, 0.05))), 3),
                )
            )
    return rows


def calm(run_id: str = "run-calme", **changes):
    return run_rows(run_id, speed=0.92, flow=8.0, occupancy=0.15, **changes)


def rush(run_id: str = "run-pointe", **changes):
    """Même réseau, vitesses effondrées, débit et occupation en hausse : une dérive franche."""
    changes.setdefault("day", 1)
    return run_rows(run_id, speed=0.45, flow=14.0, occupancy=0.55, **changes)


def moderately_slower(run_id: str = "run-un-peu-plus-lent", **changes):
    """Un demi-écart-type de moins en vitesse : de quoi avertir, pas de quoi alerter."""
    changes.setdefault("seed", 7)
    changes.setdefault("day", 1)
    return run_rows(run_id, speed=0.895, flow=8.5, occupancy=0.16, **changes)
