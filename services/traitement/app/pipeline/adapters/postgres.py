"""Écriture dans l'entrepôt PostgreSQL (`dwh`), compte `svc_traitement` : le seul qui écrit.

La lecture (API de consultation) se fait par un autre compte, `svc_lecture`, qui ne peut rien
écrire : l'écriture (ce pipeline) et la lecture (l'API) ne partagent ni compte ni code.

- **Exécution** : la première fois qu'un `run_id` apparaît, il est enregistré dans `dwh.dim_run`
  avec sa provenance complète (sans quoi la vue `dwh.v_indicator` ne servirait pas ses faits). Un
  `run_id` déjà connu avec **une autre** provenance (`source_type`) est refusé : ses faits seraient
  invisibles pour l'API.
- **Fait** : écriture idempotente sur la clé (tronçon, début, taille, run) : un rejeu met à jour la
  ligne, jamais ne la duplique. Les valeurs sont écrites telles que publiées (déjà arrondies à la
  précision des colonnes par le flux, donc aucun second arrondi).
- Chaque fait est écrit sous un point de sauvegarde : une ligne refusée par une contrainte ne fait
  pas perdre les autres.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.flux.ports import StoreFailed
from app.pipeline.facts import IndicatorFact
from app.pipeline.ports import FactFailure
from app.pipeline.reference import PlanReference, SegmentPlanInfo

logger = logging.getLogger("app.pipeline.postgres")

INSERT_RUN = text(
    """
    INSERT INTO dwh.dim_run (run_id, source_type, scenario_id, seed, dataset_id)
    VALUES (:run_id, :source_type, :scenario_id, :seed, :dataset_id)
    ON CONFLICT (run_id) DO NOTHING
    """
)
SELECT_RUN = text("SELECT source_type FROM dwh.dim_run WHERE run_id = :run_id")
UPSERT_FACT = text(
    """
    INSERT INTO dwh.fact_traffic_window AS f
        (road_segment_key, window_start, window_size_s, run_id, source_type, vehicle_count,
         flow_veh_per_min, average_speed_kmh, occupancy_rate, max_queue_length_m, speed_ratio,
         sample_count, expected_sample_count, congestion_state, classifier_version)
    SELECT r.road_segment_key, :window_start, :window_size_s, :run_id, :source_type, :vehicle_count,
           :flow_veh_per_min, :average_speed_kmh, :occupancy_rate, :max_queue_length_m,
           :speed_ratio, :sample_count, :expected_sample_count, :congestion_state,
           :classifier_version
    FROM dwh.dim_road_segment r
    JOIN dwh.dim_intersection i ON i.intersection_key = r.intersection_key
    WHERE r.road_segment_id = :road_segment_id AND i.intersection_id = :intersection_id
    ON CONFLICT (road_segment_key, window_start, window_size_s, run_id) DO UPDATE SET
        source_type = EXCLUDED.source_type,
        vehicle_count = EXCLUDED.vehicle_count,
        flow_veh_per_min = EXCLUDED.flow_veh_per_min,
        average_speed_kmh = EXCLUDED.average_speed_kmh,
        occupancy_rate = EXCLUDED.occupancy_rate,
        max_queue_length_m = EXCLUDED.max_queue_length_m,
        speed_ratio = EXCLUDED.speed_ratio,
        sample_count = EXCLUDED.sample_count,
        expected_sample_count = EXCLUDED.expected_sample_count,
        congestion_state = EXCLUDED.congestion_state,
        classifier_version = EXCLUDED.classifier_version,
        loaded_at = now()
    """
)
SEGMENTS_SQL = text(
    """
    SELECT r.road_segment_id, i.intersection_id, r.approach, r.lane_count
    FROM dwh.dim_road_segment r
    JOIN dwh.dim_intersection i ON i.intersection_key = r.intersection_key
    """
)


class _Refused(Exception):
    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code, self.reason = code, reason


def _utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


class WarehouseWriter:
    def __init__(self, url: str) -> None:
        self._engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)
        self._known_runs: dict[str, str] = {}  # run_id -> source_type déjà vérifié

    def load_plan_reference(self) -> PlanReference:
        try:
            with self._engine.connect() as connection:
                rows = connection.execute(SEGMENTS_SQL).all()
        except SQLAlchemyError as error:
            raise StoreFailed(type(error).__name__) from error
        return PlanReference(
            {
                row.road_segment_id: SegmentPlanInfo(
                    row.road_segment_id, row.intersection_id, row.approach, row.lane_count
                )
                for row in rows
            }
        )

    def load(self, facts: list[IndicatorFact]) -> list[FactFailure]:
        failures: list[FactFailure] = []
        verified: dict[str, str] = {}
        try:
            with self._engine.begin() as connection:
                for fact in facts:
                    try:
                        with connection.begin_nested():
                            self._write(connection, fact)
                        verified[fact.run_id] = fact.source_type
                    except _Refused as refusal:
                        failures.append(FactFailure(fact, refusal.code, refusal.reason))
                    except (
                        DBAPIError
                    ) as error:  # contrainte violée, type refusé : cette ligne seule
                        reason = f"ligne refusée par l'entrepôt ({type(error.orig).__name__})"
                        failures.append(FactFailure(fact, "PROCESSING_FAILED", reason))
        except SQLAlchemyError as error:
            logger.error("entrepôt non écrit", extra={"fields": {"error": type(error).__name__}})
            raise StoreFailed(type(error).__name__) from error
        self._known_runs.update(verified)  # seulement après validation de la transaction
        return failures

    def _write(self, connection, fact: IndicatorFact) -> None:
        self._register_run(connection, fact)
        written = connection.execute(
            UPSERT_FACT,
            {
                "window_start": _utc(fact.window_start_ms),
                "window_size_s": fact.window_size_s,
                "run_id": fact.run_id,
                "source_type": fact.source_type,
                "vehicle_count": fact.vehicle_count,
                "flow_veh_per_min": fact.flow_veh_per_min,
                "average_speed_kmh": fact.average_speed_kmh,
                "occupancy_rate": fact.occupancy_rate,
                "max_queue_length_m": fact.max_queue_length_m,
                "speed_ratio": fact.speed_ratio,
                "sample_count": fact.sample_count,
                "expected_sample_count": fact.expected_sample_count,
                "congestion_state": fact.congestion_state,
                "classifier_version": fact.classifier_version,
                "road_segment_id": fact.road_segment_id,
                "intersection_id": fact.intersection_id,
            },
        ).rowcount
        if written == 0:
            raise _Refused(
                "SEMANTIC_VIOLATION",
                f"tronçon {fact.road_segment_id} inconnu de {fact.intersection_id} dans dwh",
            )

    def _register_run(self, connection, fact: IndicatorFact) -> None:
        if self._known_runs.get(fact.run_id) == fact.source_type:
            return
        connection.execute(
            INSERT_RUN,
            {
                "run_id": fact.run_id,
                "source_type": fact.source_type,
                "scenario_id": fact.scenario_id,
                "seed": fact.seed,
                "dataset_id": fact.dataset_id,
            },
        )
        registered = connection.execute(SELECT_RUN, {"run_id": fact.run_id}).scalar_one()
        if registered != fact.source_type:
            raise _Refused(
                "SEMANTIC_VIOLATION",
                f"exécution {fact.run_id} déjà enregistrée avec une autre provenance "
                f"({registered})",
            )

    def close(self) -> None:
        self._engine.dispose()
