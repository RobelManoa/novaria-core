"""Lecture des indicateurs dans l'entrepôt, par la vue `dwh.v_indicator` (BE-04).

Lecture seule : aucune requête d'écriture dans ce module, et la session est ouverte en lecture seule
(`app/db/session.py`). Les services ne dépendent que de `IndicatorRepository`.

Tri de toute liste : `window_start` décroissant, puis tronçon, puis exécution (ordre d'octets,
`COLLATE "C"`, le même sur toutes les bases). Ce triplet est la position d'un curseur de pagination.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    and_,
    or_,
    select,
    tuple_,
)
from sqlalchemy.orm import Session

DEFAULT_WINDOW_SIZE_S = 60

_metadata = MetaData(schema="dwh")
V_INDICATOR = Table(
    "v_indicator",
    _metadata,
    Column("indicator_id", Text),
    Column("road_segment_id", Text),
    Column("intersection_id", Text),
    Column("window_start", DateTime(timezone=True)),
    Column("window_size_s", SmallInteger),
    Column("vehicle_count", Integer),
    Column("flow_veh_per_min", Numeric(asdecimal=False)),
    Column("average_speed_kmh", Numeric(asdecimal=False)),
    Column("occupancy_rate", Numeric(asdecimal=False)),
    Column("max_queue_length_m", Numeric(asdecimal=False)),
    Column("speed_ratio", Numeric(asdecimal=False)),
    Column("sample_count", SmallInteger),
    Column("expected_sample_count", SmallInteger),
    Column("completeness", Numeric(asdecimal=False)),
    Column("congestion_state", Text),
    Column("classifier_version", Text),
    Column("run_id", Text),
    Column("source_type", Text),
    Column("scenario_id", Text),
    Column("seed", BigInteger),
    Column("dataset_id", Text),
)
_COLUMNS = V_INDICATOR.c


@dataclass(frozen=True)
class IndicatorRow:
    """Une ligne de `dwh.v_indicator` : un tronçon, une fenêtre, une exécution."""

    indicator_id: str
    road_segment_id: str
    intersection_id: str
    window_start: datetime
    window_size_s: int
    vehicle_count: int
    flow_veh_per_min: float
    average_speed_kmh: float | None
    occupancy_rate: float | None
    max_queue_length_m: float | None
    speed_ratio: float | None
    sample_count: int
    expected_sample_count: int
    completeness: float
    congestion_state: str
    classifier_version: str
    run_id: str
    source_type: str
    scenario_id: str | None
    seed: int | None
    dataset_id: str | None


@dataclass(frozen=True)
class IndicatorFilters:
    window_size_s: int = DEFAULT_WINDOW_SIZE_S
    intersection_id: str | None = None
    road_segment_id: str | None = None
    start: datetime | None = None  # inclus
    end: datetime | None = None  # exclu
    congestion_state: str | None = None
    run_id: str | None = None
    source_type: str | None = None


Position = tuple[
    datetime, str, str
]  # (window_start, road_segment_id, run_id) de la dernière ligne vue


class IndicatorRepository(Protocol):
    def list_page(
        self, filters: IndicatorFilters, *, limit: int, after: Position | None
    ) -> list[IndicatorRow]:
        """Au plus `limit` indicateurs après `after`, dans l'ordre décrit en tête de module."""

    def get(
        self, *, run_id: str, road_segment_id: str, window_size_s: int, window_start: datetime
    ) -> IndicatorRow | None: ...

    def latest(self, *, intersection_id: str | None, run_id: str | None) -> list[IndicatorRow]:
        """Dernière fenêtre d'une minute de chaque tronçon (run le plus récent par défaut)."""


def _bytes_order(column):
    return column.collate("C")


class SqlIndicatorRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _rows(self, query) -> list[IndicatorRow]:
        return [IndicatorRow(**row._mapping) for row in self._session.execute(query)]

    def list_page(
        self, filters: IndicatorFilters, *, limit: int, after: Position | None
    ) -> list[IndicatorRow]:
        c = _COLUMNS
        query = select(V_INDICATOR).where(c.window_size_s == filters.window_size_s)
        for column, value in (
            (c.intersection_id, filters.intersection_id),
            (c.road_segment_id, filters.road_segment_id),
            (c.congestion_state, filters.congestion_state),
            (c.run_id, filters.run_id),
            (c.source_type, filters.source_type),
        ):
            if value is not None:
                query = query.where(column == value)
        if filters.start is not None:
            query = query.where(c.window_start >= filters.start)
        if filters.end is not None:
            query = query.where(c.window_start < filters.end)
        segment, run = _bytes_order(c.road_segment_id), _bytes_order(c.run_id)
        if after is not None:
            last_start, last_segment, last_run = after
            query = query.where(
                or_(
                    c.window_start < last_start,
                    and_(
                        c.window_start == last_start,
                        tuple_(segment, run) > tuple_(last_segment, last_run),
                    ),
                )
            )
        return self._rows(query.order_by(c.window_start.desc(), segment, run).limit(limit))

    def get(
        self, *, run_id: str, road_segment_id: str, window_size_s: int, window_start: datetime
    ) -> IndicatorRow | None:
        c = _COLUMNS
        query = select(V_INDICATOR).where(
            c.run_id == run_id,
            c.road_segment_id == road_segment_id,
            c.window_size_s == window_size_s,
            c.window_start == window_start,
        )
        rows = self._rows(query)
        return rows[0] if rows else None

    def latest(self, *, intersection_id: str | None, run_id: str | None) -> list[IndicatorRow]:
        c = _COLUMNS
        minute = c.window_size_s == DEFAULT_WINDOW_SIZE_S
        if run_id is None:
            newest = (
                select(c.run_id)
                .where(minute)
                .order_by(c.window_start.desc(), _bytes_order(c.run_id))
                .limit(1)
                .scalar_subquery()
            )
            run_filter = c.run_id == newest
        else:
            run_filter = c.run_id == run_id
        segment = _bytes_order(c.road_segment_id)
        query = select(V_INDICATOR).where(minute, run_filter)
        if intersection_id is not None:
            query = query.where(c.intersection_id == intersection_id)
        return self._rows(query.distinct(segment).order_by(segment, c.window_start.desc()))
