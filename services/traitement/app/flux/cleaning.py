"""Nettoyage d'un message de `iot.raw` : octets vers une mesure acceptée, ou un rejet motivé.

Règles de qualité DQ-01 à DQ-10. La collecte a déjà validé le message (schéma et règles entre
champs) ; le consommateur le revérifie, car un message publié par un autre producteur ou rejoué
depuis un fichier n'a pas ce filet. Il juge en plus ce que la collecte ne peut pas juger
(docs/03-donnees/collecte.md, section 4) :

- `UNKNOWN_SENSOR` (DQ-02) : le capteur ou son tronçon n'est pas dans le référentiel `dwh.dim_*` ;
- `FUTURE_TIMESTAMP` (DQ-10) : horodatage plus de 5 s après l'horloge (désactivé en rejeu) ;
- `LATE` (DQ-04) : jugé plus loin, par le filigrane des fenêtres (`windows.py`).

Un motif donne le chemin et le message du défaut, jamais la valeur refusée (un secret possible).
"""

import json
from datetime import UTC, datetime

from pydantic import ValidationError

from app.schemas.events import MeasurementEvent

from .model import Measurement, Referential, Rejection
from .rules import FUTURE_TOLERANCE_S

MEASUREMENT_TYPE = "novaria.iot.measurement.v1"
MAX_ERRORS_SHOWN = 5


def reject_constant(name: str) -> None:
    raise ValueError(f"constante JSON refusée : {name}")


def epoch_ms(text: str) -> int:
    return int(
        datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).timestamp() * 1000
    )


def key_text(key: bytes | None) -> str | None:
    return None if key is None else key.decode("utf-8", errors="replace")[:200]


def _intersection_of(document: object) -> str | None:
    """Le carrefour d'un message refusé, s'il est lisible et bien formé (sinon `UNKNOWN`)."""
    if isinstance(document, dict) and isinstance(document.get("data"), dict):
        candidate = document["data"].get("intersection_id")
        if (
            isinstance(candidate, str)
            and candidate.startswith("INT_")
            and candidate[4:].isdigit()
            and len(candidate) >= 6
        ):
            return candidate
    return None


def _window_start_ms(document: object, window_s: int = 60) -> int | None:
    """Début de la fenêtre d'une minute du message, pour compter le rejet par fenêtre.

    `None` si l'instant est illisible.
    """
    try:
        data = document["data"]  # type: ignore[index]
        end = epoch_ms(document["time"])  # type: ignore[index]
        start = end - int(data["interval_s"]) * 1000
    except (KeyError, TypeError, ValueError):
        return None
    return start - start % (window_s * 1000)


def describe_errors(error: ValidationError) -> str:
    """« chemin : message » pour chaque défaut ; la valeur reçue n'est jamais reprise."""
    parts = [
        f"{'/'.join(str(p) for p in item['loc'])} : {item['msg']}"
        for item in error.errors(include_input=False)
    ]
    more = len(parts) - MAX_ERRORS_SHOWN
    shown = "; ".join(parts[:MAX_ERRORS_SHOWN])
    return shown + (f" (et {more} autre{'s' if more > 1 else ''})" if more > 0 else "")


def clean(
    raw: bytes,
    referential: Referential,
    *,
    key: bytes | None = None,
    now_ms: int | None = None,
    partition: int | None = None,
    offset: int | None = None,
) -> Measurement | Rejection:
    """Rend la mesure acceptée, ou le rejet.

    `now_ms` : horloge du consommateur ; `None` désactive DQ-10 (rejeu).
    """
    where = {"original_key": key_text(key), "partition": partition, "offset": offset}
    try:
        text = raw.decode("utf-8")
        document = json.loads(text, parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError) as error:
        shown = raw.decode("utf-8", errors="replace")
        return Rejection(
            "UNREADABLE", f"message illisible ({type(error).__name__})", shown, **where
        )

    if not isinstance(document, dict):
        return Rejection(
            "CONTRACT_VIOLATION", "le message n'est pas un objet JSON", document, **where
        )
    intersection = _intersection_of(document)
    window_start = _window_start_ms(document)
    context = {**where, "intersection_id": intersection, "window_start_ms": window_start}

    declared = document.get("type")
    if isinstance(declared, str) and declared != MEASUREMENT_TYPE:
        return Rejection(
            "UNKNOWN_TYPE",
            f"type d'événement non accepté sur iot.raw : {declared[:80]}",
            document,
            **context,
        )

    try:
        event = MeasurementEvent.model_validate(document)
    except ValidationError as error:
        return Rejection("CONTRACT_VIOLATION", describe_errors(error), document, **context)

    data = event.data
    time_ms = epoch_ms(event.time)
    problems = []
    if event.subject != data.intersection_id:
        problems.append("subject doit être égal à data.intersection_id")
    if event.id != f"{data.provenance.run_id}:{data.sensor_id}:{time_ms}":
        problems.append("id attendu : <run_id>:<sensor_id>:<instant en millisecondes>")
    flags = set(data.quality.flags or [])
    if data.quality.status == "PARTIAL" and not flags & {"MISSING_SPEED", "MISSING_OCCUPANCY"}:
        problems.append("qualité PARTIAL : drapeau MISSING_SPEED ou MISSING_OCCUPANCY attendu")
    if data.quality.status == "SUSPECT" and "IMPLAUSIBLE_VALUE" not in flags:
        problems.append("qualité SUSPECT : drapeau IMPLAUSIBLE_VALUE attendu")
    if problems:
        return Rejection("SEMANTIC_VIOLATION", "; ".join(problems), document, **context)

    sensor = referential.sensors.get(data.sensor_id)
    if sensor is None:
        return Rejection(
            "UNKNOWN_SENSOR",
            "capteur absent du référentiel",
            document,
            road_segment_id=data.road_segment_id,
            **context,
        )
    if (
        sensor.road_segment_id != data.road_segment_id
        or sensor.intersection_id != data.intersection_id
    ):
        return Rejection(
            "UNKNOWN_SENSOR",
            "tronçon ou carrefour différent de celui du capteur dans le référentiel",
            document,
            road_segment_id=data.road_segment_id,
            **context,
        )
    if data.road_segment_id not in referential.segments:
        return Rejection(
            "UNKNOWN_SENSOR",
            "tronçon absent du référentiel",
            document,
            road_segment_id=data.road_segment_id,
            **context,
        )

    if now_ms is not None and time_ms > now_ms + FUTURE_TOLERANCE_S * 1000:
        return Rejection(
            "FUTURE_TIMESTAMP",
            f"horodatage à plus de {FUTURE_TOLERANCE_S} s dans le futur",
            document,
            road_segment_id=data.road_segment_id,
            **context,
        )

    provenance = data.provenance
    return Measurement(
        id=event.id,
        run_id=provenance.run_id,
        source_type=provenance.source_type,
        scenario_id=provenance.scenario_id,
        seed=provenance.seed,
        dataset_id=provenance.dataset_id,
        sensor_id=data.sensor_id,
        road_segment_id=data.road_segment_id,
        intersection_id=data.intersection_id,
        time_ms=time_ms,
        interval_s=data.interval_s,
        vehicle_count=data.vehicle_count,
        speed_kmh=data.average_speed_kmh,
        occupancy_rate=data.occupancy_rate,
        queue_length_m=data.queue_length_m,
        status=data.quality.status,
        flags=tuple(data.quality.flags or ()),
        correlation_id=event.correlation_id,
        partition=partition,
        offset=offset,
    )
