"""Indicateurs de test : exemples du contrat, modifiables champ par champ."""

import copy
import json
from datetime import UTC, datetime

from tests.unit.flux.support import epoch_ms, example


def stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def indicator(
    *,
    name: str = "indicateur-fluide.json",
    segment: str | None = None,
    intersection: str | None = None,
    start_ms: int | None = None,
    state: str | None = None,
    run: str | None = None,
    **data,
) -> dict:
    """Un événement d'indicateur conforme ; `id`, `time` et `subject` suivent les champs changés."""
    event = copy.deepcopy(example(name))
    d = event["data"]
    if run:
        d["provenance"]["run_id"] = run
    if segment:
        d["road_segment_id"] = segment
    if intersection:
        d["intersection_id"] = intersection
        event["subject"] = intersection
    if state:
        d["congestion_state"] = state
    d.update(data)
    if start_ms is not None:
        d["window_start"] = stamp(start_ms)
    start = epoch_ms(d["window_start"])
    event["time"] = stamp(start + d["window_size_s"] * 1000)
    event["id"] = f"{d['provenance']['run_id']}:{d['road_segment_id']}:{d['window_size_s']}:{start}"
    event["correlation_id"] = f"corr-{start}"
    return event


def raw(event: dict) -> bytes:
    return json.dumps(event).encode("utf-8")
