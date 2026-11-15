"""Prévision de référence par persistance (IA-06, ADR-015).

La référence que tout modèle doit battre : la vitesse de demain est celle d'aujourd'hui. Pour chaque
tronçon, la prévision à l'horizon demandé est le ratio de vitesse de la dernière fenêtre d'une
minute connue, dans l'exécution la plus récente de l'entrepôt ; l'état prévu est celui de cette
fenêtre.

Ce n'est pas un modèle entraîné : `model.kind` vaut `REFERENCE`, sans exécution d'entraînement, sans
date d'entraînement ni métrique. L'émission est la fin de la dernière fenêtre ; elle reste celle de
la dernière donnée si l'entrepôt n'a rien reçu depuis (le client la lit dans `issued_at`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.repositories.indicators import IndicatorRepository, IndicatorRow

REFERENCE_NAME = "persistance"
REFERENCE_VERSION = "1"
WINDOW = timedelta(seconds=60)


class ForecastUnavailable(Exception):
    """L'entrepôt n'a aucune fenêtre exploitable : ni modèle ni référence ne peuvent répondre."""


@dataclass(frozen=True)
class ReferenceForecast:
    row: IndicatorRow  # la dernière fenêtre connue du tronçon : ratio, état et provenance
    issued_at: datetime
    horizon_min: int
    target_time: datetime
    predicted_speed_ratio: float


class ForecastService:
    def __init__(self, indicators: IndicatorRepository) -> None:
        self._indicators = indicators

    def persistence(
        self, *, horizon_min: int, road_segment_ids: Sequence[str] | None = None
    ) -> list[ReferenceForecast]:
        """Une prévision par tronçon demandé (tous si aucun), triée par identifiant.

        Un tronçon inconnu, ou dont la dernière fenêtre n'a pas de ratio de vitesse (route vide),
        n'a pas de prévision : il est absent de la liste, jamais rempli par une valeur inventée.
        """
        rows = self._indicators.latest(intersection_id=None, run_id=None)
        if not rows:
            raise ForecastUnavailable
        wanted = set(road_segment_ids) if road_segment_ids else None
        forecasts = []
        for row in sorted(rows, key=lambda r: r.road_segment_id.encode()):
            if row.speed_ratio is None or (
                wanted is not None and row.road_segment_id not in wanted
            ):
                continue
            issued_at = row.window_start + WINDOW
            forecasts.append(
                ReferenceForecast(
                    row=row,
                    issued_at=issued_at,
                    horizon_min=horizon_min,
                    target_time=issued_at + timedelta(minutes=horizon_min),
                    predicted_speed_ratio=row.speed_ratio,
                )
            )
        return forecasts
