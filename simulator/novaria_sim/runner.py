"""Exécute un `Run` vers une ou plusieurs destinations, au débit demandé."""

import threading
from dataclasses import dataclass

from .pacing import Pacer
from .run import Run


@dataclass
class Stats:
    delivered: int = 0
    truth_rows: int = 0
    intervals: int = 0
    stopped: bool = False


def execute(run: Run, sinks, truth=None, pacer: Pacer | None = None, stop: threading.Event | None = None,
            stats: Stats | None = None) -> Stats:
    """Déroule le run jusqu'au bout (ou jusqu'à `stop`), puis livre les messages en retard qui attendent encore.

    `truth` reçoit une ligne de vérité terrain par capteur et par intervalle, `sinks` les messages dans l'ordre de
    livraison. Le débit ne freine que les messages : il ne change aucune valeur.
    """
    stats = stats or Stats()
    pacer = pacer or Pacer(None)

    def deliver(deliveries) -> bool:
        """Faux si l'arrêt a été demandé : vérifié avant CHAQUE message, car à bas débit un intervalle dure longtemps."""
        for delivery in deliveries:
            if stop is not None and stop.is_set():
                stats.stopped = True
                return False
            pacer.wait()
            for sink in sinks:
                sink.send(delivery)
            stats.delivered += 1
        return True

    while not run.done:
        if stop is not None and stop.is_set():
            stats.stopped = True
            return stats
        tick = run.step()
        stats.intervals += 1
        if truth is not None:
            for row in tick.truth:
                truth.write(row)
        stats.truth_rows += len(tick.truth)
        if not deliver(tick.deliveries):
            return stats
    deliver(run.finish())
    return stats
