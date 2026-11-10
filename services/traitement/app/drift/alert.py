"""Alerte locale : une ligne de journal JSON par dérive détectée (ADR-025, équivalent d'une alarme).

La ligne porte l'état, les variables en cause avec leur PSI et les deux exécutions comparées : de
quoi retrouver la donnée dans l'entrepôt.
"""

import logging

from app.drift.monitor import DriftReport

logger = logging.getLogger("app.drift")
ALERT_MESSAGE = "dérive des entrées détectée"
CLEARED_MESSAGE = "dérive des entrées terminée"


def alert_fields(report: DriftReport) -> dict[str, object]:
    return {
        "event": "input_drift",
        "status": report.status.value,
        "reference_run_id": report.reference_run_id,
        "current_run_id": report.current_run_id,
        "alert_threshold": report.thresholds.alert,
        "features": {f.feature: round(f.psi, 4) for f in report.drifting},
        "means": {
            f.feature: {
                "reference": round(f.reference_mean, 4),
                "current": round(f.current_mean, 4),
            }
            for f in report.drifting
        },
    }


def emit_alert(report: DriftReport) -> None:
    logger.warning(ALERT_MESSAGE, extra={"fields": alert_fields(report)})


def emit_cleared(report: DriftReport) -> None:
    logger.info(
        CLEARED_MESSAGE, extra={"fields": {"event": "input_drift", "status": report.status.value}}
    )
