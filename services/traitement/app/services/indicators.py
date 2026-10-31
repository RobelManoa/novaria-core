"""Lecture des indicateurs : pagination par curseur et identifiant d'indicateur (BE-04).

Identifiant : `<run_id>:<tronçon>:<taille de fenêtre>:<début en millisecondes depuis 1970>`, égal à
l'attribut `id` de l'événement `novaria.traffic.indicator.v1`. Il se lit de droite à gauche : le
`run_id` peut lui-même contenir des deux-points.
"""

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.repositories.indicators import (
    IndicatorFilters,
    IndicatorRepository,
    IndicatorRow,
    Position,
)

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
WINDOW_SIZES = (60, 300)
SEGMENT_PATTERN = re.compile(r"ROAD_[0-9]{3,}")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class InvalidCursor(ValueError):
    """Le curseur n'a pas été produit par ce service."""


@dataclass(frozen=True)
class IndicatorPage:
    items: list[IndicatorRow]
    next_cursor: str | None


def make_indicator_id(
    run_id: str, road_segment_id: str, window_size_s: int, window_start: datetime
) -> str:
    milliseconds = (window_start - EPOCH) // timedelta(milliseconds=1)
    return f"{run_id}:{road_segment_id}:{window_size_s}:{milliseconds}"


def parse_indicator_id(indicator_id: str) -> tuple[str, str, int, datetime] | None:
    """Rend (run_id, tronçon, taille, début) ou `None` si l'identifiant n'a pas cette forme."""
    parts = indicator_id.rsplit(":", 3)
    if len(parts) != 4:
        return None
    run_id, segment, size, milliseconds = parts
    if not (1 <= len(run_id) <= 80) or not SEGMENT_PATTERN.fullmatch(segment):
        return None
    if size not in {str(s) for s in WINDOW_SIZES} or not milliseconds.isascii():
        return None
    if not milliseconds.isdecimal():
        return None
    try:
        start = EPOCH + timedelta(milliseconds=int(milliseconds))
    except OverflowError:
        return None
    return run_id, segment, int(size), start


def encode_cursor(row: IndicatorRow) -> str:
    raw = json.dumps([row.window_start.isoformat(), row.road_segment_id, row.run_id])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Position:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        moment, segment, run = json.loads(raw)
        if not isinstance(segment, str) or not isinstance(run, str):
            raise ValueError("types")
        start = datetime.fromisoformat(moment)
        if start.tzinfo is None:
            raise ValueError("fuseau")
        return start, segment, run
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as error:
        raise InvalidCursor(cursor) from error


class IndicatorService:
    def __init__(self, indicators: IndicatorRepository) -> None:
        self._indicators = indicators

    def list_page(
        self, filters: IndicatorFilters, *, limit: int = DEFAULT_LIMIT, cursor: str | None = None
    ) -> IndicatorPage:
        after = decode_cursor(cursor) if cursor else None
        rows = self._indicators.list_page(filters, limit=limit + 1, after=after)
        page = rows[:limit]
        more = len(rows) > limit
        return IndicatorPage(page, encode_cursor(page[-1]) if more else None)

    def get(self, indicator_id: str) -> IndicatorRow | None:
        key = parse_indicator_id(indicator_id)
        if key is None:
            return None
        run_id, segment, size, start = key
        return self._indicators.get(
            run_id=run_id, road_segment_id=segment, window_size_s=size, window_start=start
        )

    def latest(self, *, intersection_id: str | None, run_id: str | None) -> list[IndicatorRow]:
        return self._indicators.latest(intersection_id=intersection_id, run_id=run_id)
