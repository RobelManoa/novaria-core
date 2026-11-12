"""Le moniteur de dérive du processus, construit depuis la configuration."""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.drift.monitor import Thresholds
from app.drift.service import DriftMonitor


def build_monitor(settings: Settings) -> DriftMonitor:
    return DriftMonitor(
        reference_run_id=settings.drift_reference_run_id or None,
        thresholds=Thresholds(
            warn=settings.drift_warn_psi,
            alert=settings.drift_alert_psi,
            min_samples=settings.drift_min_samples,
        ),
        max_rows=settings.drift_max_rows,
        cache_s=settings.drift_cache_s,
    )


@lru_cache
def get_drift_monitor() -> DriftMonitor:
    return build_monitor(get_settings())
