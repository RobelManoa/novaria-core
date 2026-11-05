"""Un indicateur lu sur `traffic.indicators` : octets vers un fait à écrire, ou un rejet motivé.

Le service de flux publie des événements conformes ; le pipeline les revérifie, car un message
venu d'ailleurs (rejeu d'un fichier, autre producteur) n'a pas ce filet. Contrôles : JSON lisible,
type attendu, schéma, puis les règles entre champs que le schéma ne dit pas (README des contrats) :
`subject` = carrefour, `id` = `<run>:<tronçon>:<taille>:<début en ms>`, fenêtre alignée sur sa
taille, `time` = fin de fenêtre, `sample_count` au plus le double de l'attendu.
"""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.flux.cleaning import describe_errors, epoch_ms, key_text, reject_constant
from app.flux.model import Rejection
from app.schemas.events import IndicatorEvent

INDICATOR_TYPE = "novaria.traffic.indicator.v1"


@dataclass(frozen=True)
class IndicatorFact:
    """Une ligne de `dwh.fact_traffic_window`, avec la provenance de son exécution."""

    event_id: str
    road_segment_id: str
    intersection_id: str
    window_start_ms: int
    window_size_s: int
    vehicle_count: int
    flow_veh_per_min: float
    average_speed_kmh: float | None
    occupancy_rate: float | None
    max_queue_length_m: float | None
    speed_ratio: float | None
    sample_count: int
    expected_sample_count: int
    congestion_state: str
    classifier_version: str
    run_id: str
    source_type: str
    scenario_id: str | None
    seed: int | None
    dataset_id: str | None
    partition: int | None = None
    offset: int | None = None

    @property
    def window_end_ms(self) -> int:
        return self.window_start_ms + self.window_size_s * 1000

    @property
    def provenance(self) -> dict:
        provenance: dict = {"source_type": self.source_type, "run_id": self.run_id}
        for name in ("scenario_id", "seed", "dataset_id"):
            if getattr(self, name) is not None:
                provenance[name] = getattr(self, name)
        return provenance


def parse_indicator(
    raw: bytes,
    *,
    key: bytes | None = None,
    partition: int | None = None,
    offset: int | None = None,
) -> IndicatorFact | Rejection:
    where = {"original_key": key_text(key), "partition": partition, "offset": offset}
    try:
        document = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError) as error:
        shown = raw.decode("utf-8", errors="replace")
        return Rejection(
            "UNREADABLE", f"message illisible ({type(error).__name__})", shown, **where
        )
    if not isinstance(document, dict):
        return Rejection(
            "CONTRACT_VIOLATION", "le message n'est pas un objet JSON", document, **where
        )

    data = document.get("data") if isinstance(document.get("data"), dict) else {}
    candidate = data.get("intersection_id")
    intersection = candidate if isinstance(candidate, str) and _is_intersection(candidate) else None
    context = {**where, "intersection_id": intersection}

    declared = document.get("type")
    if isinstance(declared, str) and declared != INDICATOR_TYPE:
        reason = f"type d'événement non accepté sur traffic.indicators : {declared[:80]}"
        return Rejection("UNKNOWN_TYPE", reason, document, **context)
    try:
        event = IndicatorEvent.model_validate(document)
    except ValidationError as error:
        return Rejection("CONTRACT_VIOLATION", describe_errors(error), document, **context)

    problems = _semantic_problems(event)
    if problems:
        return Rejection("SEMANTIC_VIOLATION", "; ".join(problems), document, **context)

    d, provenance = event.data, event.data.provenance
    return IndicatorFact(
        event_id=event.id,
        road_segment_id=d.road_segment_id,
        intersection_id=d.intersection_id,
        window_start_ms=epoch_ms(d.window_start),
        window_size_s=d.window_size_s,
        vehicle_count=d.vehicle_count,
        flow_veh_per_min=d.flow_veh_per_min,
        average_speed_kmh=d.average_speed_kmh,
        occupancy_rate=d.occupancy_rate,
        max_queue_length_m=d.max_queue_length_m,
        speed_ratio=d.speed_ratio,
        sample_count=d.sample_count,
        expected_sample_count=d.expected_sample_count,
        congestion_state=d.congestion_state,
        classifier_version=d.classifier_version,
        run_id=provenance.run_id,
        source_type=provenance.source_type,
        scenario_id=provenance.scenario_id,
        seed=provenance.seed,
        dataset_id=provenance.dataset_id,
        partition=partition,
        offset=offset,
    )


def _is_intersection(value: str) -> bool:
    return value.startswith("INT_") and value[4:].isdigit() and len(value) >= 6


def _semantic_problems(event: IndicatorEvent) -> list[str]:
    d = event.data
    start = epoch_ms(d.window_start)
    size_ms = d.window_size_s * 1000
    problems = []
    if event.subject != d.intersection_id:
        problems.append("subject doit être égal à data.intersection_id")
    expected_id = f"{d.provenance.run_id}:{d.road_segment_id}:{d.window_size_s}:{start}"
    if event.id != expected_id:
        problems.append("id attendu : <run_id>:<tronçon>:<taille>:<début de fenêtre en ms>")
    if start % size_ms:
        problems.append("la fenêtre doit être alignée sur sa taille")
    if epoch_ms(event.time) != start + size_ms:
        problems.append("time doit être la fin de la fenêtre")
    if d.sample_count > 2 * d.expected_sample_count:
        problems.append("sample_count dépasse le double de expected_sample_count")
    return problems
