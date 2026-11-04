"""Débit réglable : un nombre de messages par seconde, indépendant du temps simulé (essais de charge)."""

import time
from collections.abc import Callable


class Pacer:
    """Retient chaque message jusqu'à son heure : le n-ième part à `n / débit` secondes après le premier.

    Débit absent ou nul : aucun frein (écriture de fichier, charge maximale). L'horloge et l'attente sont injectables,
    ce qui permet de tester le débit sans attendre pour de vrai.
    """

    def __init__(self, rate: float | None, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if rate is not None and rate < 0:
            raise ValueError("le débit ne peut pas être négatif")
        self.rate = rate or None
        self._clock, self._sleep = clock, sleep
        self._origin: float | None = None
        self._count = 0

    def wait(self) -> None:
        if self.rate is None:
            return
        now = self._clock()
        if self._origin is None:
            self._origin = now
        deadline = self._origin + self._count / self.rate
        self._count += 1
        if deadline > now:
            self._sleep(deadline - now)
