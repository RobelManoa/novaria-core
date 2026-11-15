"""Surveillance de la dérive : lit l'entrepôt, compare, journalise l'alerte (IA-06).

`DriftMonitor` vit autant que le processus : il garde la dernière comparaison quelques secondes (un
`/metrics` interrogé toutes les secondes ne relit pas l'entrepôt à chaque fois) et ne journalise
l'alerte qu'une fois par dérive, pas à chaque lecture.
"""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from app.drift import alert
from app.drift.monitor import DriftReport, Status, Thresholds, evaluate
from app.drift.source import latest_run_id, read_samples
from app.repositories.indicators import IndicatorRepository


def compare(
    indicators: IndicatorRepository,
    *,
    reference_run_id: str | None,
    current_run_id: str | None = None,
    thresholds: Thresholds,
    max_rows: int,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DriftReport:
    """Compare l'exécution de référence à la courante (la plus récente par défaut)."""
    current_run_id = current_run_id or latest_run_id(indicators)

    def without_verdict(status: Status, reason: str) -> DriftReport:
        return DriftReport(status, now(), reference_run_id, current_run_id, thresholds, [], reason)

    if current_run_id is None:
        return without_verdict(Status.NO_DATA, "l'entrepôt ne contient aucune fenêtre")
    if not reference_run_id:
        return without_verdict(
            Status.NO_REFERENCE, "aucune exécution de référence (DRIFT_REFERENCE_RUN_ID)"
        )
    return evaluate(
        read_samples(indicators, reference_run_id, max_rows=max_rows),
        read_samples(indicators, current_run_id, max_rows=max_rows),
        checked_at=now(),
        reference_run_id=reference_run_id,
        current_run_id=current_run_id,
        thresholds=thresholds,
    )


class DriftMonitor:
    def __init__(
        self,
        *,
        reference_run_id: str | None,
        thresholds: Thresholds,
        max_rows: int,
        cache_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reference_run_id = reference_run_id
        self.thresholds = thresholds
        self.max_rows = max_rows
        self._cache_s = cache_s
        self._clock = clock
        self._lock = threading.Lock()
        self._report: DriftReport | None = None
        self._read_at = 0.0
        self._announced: tuple | None = None

    def report(self, indicators: IndicatorRepository) -> DriftReport:
        with self._lock:
            if self._report is None or self._clock() - self._read_at >= self._cache_s:
                self._report = compare(
                    indicators,
                    reference_run_id=self.reference_run_id,
                    thresholds=self.thresholds,
                    max_rows=self.max_rows,
                )
                self._read_at = self._clock()
                self._announce(self._report)
            return self._report

    def _announce(self, report: DriftReport) -> None:
        """Une ligne à l'entrée dans l'alerte (ou si la dérive change), une à la sortie."""
        if report.is_alert:
            key = (
                report.reference_run_id,
                report.current_run_id,
                tuple(f.feature for f in report.drifting),
            )
            if key != self._announced:
                alert.emit_alert(report)
            self._announced = key
        elif report.status in (Status.OK, Status.WARN):
            if self._announced is not None:
                alert.emit_cleared(report)
            self._announced = None
        # Sans verdict (entrepôt vide, pas de référence, trop peu de valeurs) : rien ne change.
