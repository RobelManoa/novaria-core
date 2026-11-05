"""Aides communes aux tests du simulateur (bibliothèque standard seulement)."""

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

SIMULATOR = Path(__file__).resolve().parents[1]
ROOT = SIMULATOR.parent
sys.path.insert(0, str(SIMULATOR))

from novaria_sim.events import to_line  # noqa: E402
from novaria_sim.run import Run, default_config  # noqa: E402

START = datetime(2026, 10, 20, 7, 30, tzinfo=UTC)


def config(scenario="heure-de-pointe", seed=42, minutes=10, start=START, run_id="run-test", anomalies=()):
    return default_config(scenario, seed, run_id, start, None, minutes * 60, tuple(anomalies))


def play(cfg):
    """Déroule un run entier : (messages dans l'ordre de livraison, lignes de vérité terrain, run)."""
    run = Run(cfg)
    deliveries, truth = [], []
    while not run.done:
        tick = run.step()
        deliveries += tick.deliveries
        truth += tick.truth
    deliveries += run.finish()
    return deliveries, truth, run


def lines(deliveries):
    return [to_line(delivery.event) for delivery in deliveries]


def digest(text_lines):
    hasher = hashlib.sha256()
    for line in text_lines:
        hasher.update((line + "\n").encode("utf-8"))
    return hasher.hexdigest()
