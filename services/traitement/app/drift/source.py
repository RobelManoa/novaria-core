"""Lecture des valeurs d'entrée d'une exécution (fenêtres d'une minute, lecture seule)."""

from app.drift.monitor import FEATURES
from app.repositories.indicators import IndicatorFilters, IndicatorRepository, IndicatorRow

PAGE_SIZE = 500
WINDOW_SIZE_S = 60


def latest_run_id(indicators: IndicatorRepository) -> str | None:
    """L'exécution de la fenêtre la plus récente de l'entrepôt, ou `None` s'il est vide."""
    rows = indicators.latest(intersection_id=None, run_id=None)
    return rows[0].run_id if rows else None


def read_samples(
    indicators: IndicatorRepository, run_id: str, *, max_rows: int
) -> dict[str, list[float]]:
    """Les valeurs non nulles de chaque variable d'entrée, sur au plus `max_rows` fenêtres.

    Les fenêtres sont lues de la plus récente à la plus ancienne : au-delà du plafond, ce sont
    les plus anciennes qui sont laissées de côté.
    """
    samples: dict[str, list[float]] = {name: [] for name in FEATURES}
    filters = IndicatorFilters(window_size_s=WINDOW_SIZE_S, run_id=run_id)
    after = None
    read = 0
    while read < max_rows:
        rows: list[IndicatorRow] = indicators.list_page(
            filters, limit=min(PAGE_SIZE, max_rows - read), after=after
        )
        if not rows:
            break
        for row in rows:
            for name in FEATURES:
                value = getattr(row, name)
                if value is not None:
                    samples[name].append(float(value))
        read += len(rows)
        last = rows[-1]
        after = (last.window_start, last.road_segment_id, last.run_id)
    return samples
