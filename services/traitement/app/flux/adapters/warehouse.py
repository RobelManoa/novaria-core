"""Entrepôt PostgreSQL (`dwh`), compte `svc_traitement` : référentiel lu, épisodes écrits.

Le référentiel (capteurs, tronçons, carrefours) est lu **une fois au démarrage** : un nouveau
capteur demande un redémarrage du service (limite connue, docs/03-donnees/flux.md).

Épisodes : écriture idempotente sur la clé d'unicité (`road_segment_key`, `run_id`, `started_at`).

- Tant que l'épisode est ouvert : le pic ne redescend pas, le ratio minimal ne remonte pas, le
  nombre de fenêtres ne baisse pas (le rejeu d'une écriture plus ancienne ne change rien).
- À la clôture : `window_count` prend la valeur **définitive** (fenêtres entre `started_at` et
  `ended_at`), qui peut être plus petite que le compte provisoire de l'épisode ouvert : celui-ci
  inclut les fenêtres de confirmation du retour au fluide.
- Une fois clos : plus rien ne change ; un rejeu ne le réouvre pas, la première clôture fait foi.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.flux.episodes import EpisodeRecord
from app.flux.model import Referential, SegmentRef, SensorRef
from app.flux.ports import StoreFailed

logger = logging.getLogger("app.flux.warehouse")

SENSORS_SQL = text(
    """
    SELECT s.sensor_id, r.road_segment_id, i.intersection_id, s.reporting_interval_s
    FROM dwh.dim_sensor s
    JOIN dwh.dim_road_segment r ON r.road_segment_key = s.road_segment_key
    JOIN dwh.dim_intersection i ON i.intersection_key = r.intersection_key
    """
)
SEGMENTS_SQL = text(
    """
    SELECT r.road_segment_id, r.road_segment_key, i.intersection_id, r.free_flow_speed_kmh
    FROM dwh.dim_road_segment r
    JOIN dwh.dim_intersection i ON i.intersection_key = r.intersection_key
    """
)
UPSERT_EPISODE_SQL = text(
    """
    INSERT INTO dwh.fact_congestion_episode AS e
        (episode_id, road_segment_key, run_id, source_type, started_at, ended_at,
         peak_state, min_speed_ratio, window_count)
    SELECT CAST(:episode_id AS uuid), r.road_segment_key, :run_id, :source_type, :started_at,
           :ended_at, :peak_state, CAST(:min_speed_ratio AS numeric), :window_count
    FROM dwh.dim_road_segment r
    WHERE r.road_segment_id = :road_segment_id
    ON CONFLICT (road_segment_key, run_id, started_at) DO UPDATE SET
        ended_at = COALESCE(e.ended_at, EXCLUDED.ended_at),
        peak_state = CASE
            WHEN e.ended_at IS NOT NULL THEN e.peak_state
            WHEN e.peak_state = 'CONGESTED' OR EXCLUDED.peak_state = 'CONGESTED' THEN 'CONGESTED'
            ELSE EXCLUDED.peak_state END,
        min_speed_ratio = CASE
            WHEN e.ended_at IS NOT NULL THEN e.min_speed_ratio
            ELSE LEAST(e.min_speed_ratio, EXCLUDED.min_speed_ratio) END,
        window_count = CASE
            WHEN e.ended_at IS NOT NULL THEN e.window_count
            WHEN EXCLUDED.ended_at IS NOT NULL THEN EXCLUDED.window_count
            ELSE GREATEST(e.window_count, EXCLUDED.window_count) END
    """
)


def _utc(ms: int | None) -> datetime | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, UTC)


class Warehouse:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)

    def load_referential(self) -> Referential:
        try:
            with self._engine.connect() as connection:
                sensors = {
                    row.sensor_id: SensorRef(
                        row.sensor_id,
                        row.road_segment_id,
                        row.intersection_id,
                        row.reporting_interval_s,
                    )
                    for row in connection.execute(SENSORS_SQL)
                }
                segments = {
                    row.road_segment_id: SegmentRef(
                        row.road_segment_id,
                        row.road_segment_key,
                        row.intersection_id,
                        float(row.free_flow_speed_kmh),
                    )
                    for row in connection.execute(SEGMENTS_SQL)
                }
        except SQLAlchemyError as error:
            raise StoreFailed(type(error).__name__) from error
        return Referential(sensors, segments)

    def upsert(self, record: EpisodeRecord) -> None:
        parameters = {
            "episode_id": record.episode_id,
            "road_segment_id": record.road_segment_id,
            "run_id": record.run_id,
            "source_type": record.source_type,
            "started_at": _utc(record.started_at_ms),
            "ended_at": _utc(record.ended_at_ms),
            "peak_state": record.peak_state,
            "min_speed_ratio": record.min_speed_ratio,
            "window_count": record.window_count,
        }
        try:
            with self._engine.begin() as connection:
                written = connection.execute(UPSERT_EPISODE_SQL, parameters).rowcount
        except SQLAlchemyError as error:
            logger.error("épisode non écrit", extra={"fields": {"error": type(error).__name__}})
            raise StoreFailed(type(error).__name__) from error
        if written == 0:
            raise StoreFailed(f"tronçon {record.road_segment_id} absent de dim_road_segment")

    def close(self) -> None:
        self._engine.dispose()
