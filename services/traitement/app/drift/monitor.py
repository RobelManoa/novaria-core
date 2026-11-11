"""Décision de dérive : un PSI par variable d'entrée, un état pour l'ensemble (IA-06).

Les variables sont les entrées d'une prévision de vitesse : le ratio de vitesse, le débit et le
taux d'occupation. Une variable qui dépasse le seuil d'alerte suffit à déclarer la dérive.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.drift.stats import population_stability_index

FEATURES = ("speed_ratio", "flow_veh_per_min", "occupancy_rate")


class Status(StrEnum):
    """Du plus sain au plus grave ; les états sans verdict viennent en dernier."""

    OK = "OK"
    WARN = "WARN"
    ALERT = "ALERT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # trop peu de valeurs pour comparer
    NO_REFERENCE = "NO_REFERENCE"  # aucune exécution de référence configurée
    NO_DATA = "NO_DATA"  # l'entrepôt est vide


@dataclass(frozen=True)
class Thresholds:
    """Valeurs de départ (ADR-017), révisées après l'essai avec dérive simulée."""

    warn: float = 0.10
    alert: float = 0.25
    min_samples: int = 100

    def __post_init__(self) -> None:
        if not 0 < self.warn < self.alert:
            raise ValueError("le seuil d'avertissement doit être positif et sous celui d'alerte")
        if self.min_samples < 10:
            raise ValueError("au moins 10 valeurs sont nécessaires pour comparer")


@dataclass(frozen=True)
class FeatureDrift:
    feature: str
    psi: float
    status: Status
    reference_count: int
    current_count: int
    reference_mean: float
    current_mean: float


@dataclass(frozen=True)
class DriftReport:
    status: Status
    checked_at: datetime
    reference_run_id: str | None
    current_run_id: str | None
    thresholds: Thresholds
    features: list[FeatureDrift] = field(default_factory=list)
    reason: str | None = None

    @property
    def is_alert(self) -> bool:
        return self.status is Status.ALERT

    @property
    def drifting(self) -> list[FeatureDrift]:
        """Les variables au-dessus du seuil d'alerte, la plus décalée d'abord."""
        over = [f for f in self.features if f.status is Status.ALERT]
        return sorted(over, key=lambda f: f.psi, reverse=True)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def classify(psi: float, thresholds: Thresholds) -> Status:
    if psi >= thresholds.alert:
        return Status.ALERT
    if psi >= thresholds.warn:
        return Status.WARN
    return Status.OK


def evaluate(
    reference: Mapping[str, Sequence[float]],
    current: Mapping[str, Sequence[float]],
    *,
    checked_at: datetime,
    reference_run_id: str | None,
    current_run_id: str | None,
    thresholds: Thresholds = Thresholds(),  # noqa: B008 : valeur immuable
) -> DriftReport:
    """Compare les distributions de chaque variable ; l'état d'ensemble est le pire des états."""

    def report(status: Status, reason: str | None = None, features=()) -> DriftReport:
        return DriftReport(
            status, checked_at, reference_run_id, current_run_id, thresholds, list(features), reason
        )

    results: list[FeatureDrift] = []
    for name in FEATURES:
        ref, cur = list(reference.get(name, ())), list(current.get(name, ()))
        if len(ref) < thresholds.min_samples or len(cur) < thresholds.min_samples:
            return report(
                Status.INSUFFICIENT_DATA,
                f"{name} : {len(ref)} valeurs de référence et {len(cur)} courantes, "
                f"{thresholds.min_samples} au moins sont nécessaires",
                results,
            )
        psi = population_stability_index(ref, cur)
        results.append(
            FeatureDrift(
                name, psi, classify(psi, thresholds), len(ref), len(cur), mean(ref), mean(cur)
            )
        )
    worst = max(results, key=lambda f: f.psi)
    return report(worst.status, features=results)
