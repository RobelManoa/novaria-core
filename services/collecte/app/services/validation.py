"""Validation d'un message reçu par la collecte : le contrat, puis les règles entre champs (MS-08).

Un message est **accepté** ou **rejeté avec un motif** ; il n'y a pas de troisième issue. Ce module
ne connaît ni HTTP, ni Kafka, ni MongoDB : il reçoit des octets et rend un `Valid` ou un
`Rejection`.

Motifs rendus (`reason_code`, énumération de `error-rejected.schema.json`) :

- `UNREADABLE` : ni UTF-8 ni JSON valide, ou message de plus de `max_bytes` octets (la charge
  d'origine est alors un texte)
- `UNKNOWN_TYPE` : `type` présent mais autre que `novaria.iot.measurement.v1` : seul ce type entre
  sur `iot.raw`
- `CONTRACT_VIOLATION` : schéma non respecté : champ inconnu ou manquant, type, borne, date sans
  fuseau, règle conditionnelle (DQ-01)
- `SEMANTIC_VIOLATION` : règle entre champs que le schéma ne sait pas exprimer : `subject` =
  `data.intersection_id`, `id` = `<run_id>:<sensor_id>:<ms>` (DQ-03), drapeaux de qualité (DQ-05,
  DQ-06)

Hors de ce module, et volontairement : `UNKNOWN_SENSOR` (DQ-02) exige le référentiel des capteurs,
que seul le traitement possède ; `LATE` (DQ-04) et `FUTURE_TIMESTAMP` (DQ-10) comparent l'horodatage
à l'horloge du consommateur, et un rejeu de données anciennes ne doit pas être refusé à l'entrée.

Les règles entre champs sont celles de `contracts/validate_events.py` ; un test compare les deux sur
des messages valides et invalides.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import ValidationError

from app.schemas.events import MeasurementEvent

MEASUREMENT_TYPE = "novaria.iot.measurement.v1"
SOURCE_TOPIC = "iot.raw"
MAX_REASON_CHARS = 2000
MAX_TEXT_PAYLOAD_CHARS = 20000  # une charge illisible est conservée sous forme de texte, tronquée
INTERSECTION = re.compile(r"INT_[0-9]{2,}")


@dataclass(frozen=True)
class Valid:
    """Un message conforme : l'objet JSON tel que reçu (c'est lui qui est publié et stocké)."""

    event: dict
    model: MeasurementEvent

    @property
    def event_id(self) -> str:
        return self.event["id"]


@dataclass(frozen=True)
class Rejection:
    reason_code: str
    reason: str
    original_payload: object  # un objet JSON, ou un texte si le message est illisible
    intersection_id: str | None = None
    original_key: str | None = None
    errors: list[dict[str, str]] = field(
        default_factory=list
    )  # champ et message, pour la réponse 422


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def instant_ms(value: str) -> int:
    """Même calcul que `contracts/validate_events.py` : l'identifiant d'une mesure en dépend."""
    return int(parse_utc(value).timestamp() * 1000)


def _never(constant: str) -> None:
    raise ValueError(f"constante JSON non permise : {constant}")


def _text(body: bytes) -> str:
    return body[:MAX_TEXT_PAYLOAD_CHARS].decode("utf-8", errors="replace")


def _trim(reason: str) -> str:
    return reason if len(reason) <= MAX_REASON_CHARS else reason[: MAX_REASON_CHARS - 1] + "…"


def _intersection_of(raw: object) -> str | None:
    """Le carrefour du message s'il est identifiable (sinon `None`, sujet `UNKNOWN` du rejet)."""
    if not isinstance(raw, dict):
        return None
    data = raw.get("data")
    candidates = [
        data.get("intersection_id") if isinstance(data, dict) else None,
        raw.get("subject"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and INTERSECTION.fullmatch(candidate):
            return candidate
    return None


def _contract_errors(error: ValidationError) -> tuple[list[dict[str, str]], str]:
    """Les défauts du contrat : (liste pour la réponse 422, motif pour `errors.dlq`).

    Réponse : `body.data.occupancy_rate`, forme des autres erreurs de validation de l'API.
    Motif : `data/occupancy_rate : ...`, forme des exemples de `contracts/events/examples/`.
    `input` n'est jamais repris : la valeur fautive peut être n'importe quoi.
    """
    items = error.errors(include_input=False, include_url=False, include_context=False)
    problems = [
        {"field": ".".join(["body", *map(str, item["loc"])]), "message": item["msg"]}
        for item in items
    ]
    reason = " ; ".join(
        f"{'/'.join(map(str, item['loc'])) or '(racine)'} : {item['msg']}" for item in items
    )
    return problems, reason


def semantic_errors(model: MeasurementEvent) -> list[str]:
    """Règles entre champs de `contracts/validate_events.py` pour une mesure."""
    errors: list[str] = []
    data = model.data
    if model.subject != data.intersection_id:
        errors.append("subject doit être égal à data.intersection_id (clé de partition)")
    expected = f"{data.provenance.run_id}:{data.sensor_id}:{instant_ms(model.time)}"
    if model.id != expected:
        errors.append(f"id de mesure attendu : {expected}")
    flags = set(data.quality.flags or [])
    if data.quality.status == "PARTIAL" and not flags & {"MISSING_SPEED", "MISSING_OCCUPANCY"}:
        errors.append(
            "qualité PARTIAL : drapeau MISSING_SPEED ou MISSING_OCCUPANCY attendu (DQ-06)"
        )
    if data.quality.status == "SUSPECT" and "IMPLAUSIBLE_VALUE" not in flags:
        errors.append("qualité SUSPECT : drapeau IMPLAUSIBLE_VALUE attendu (DQ-05)")
    return errors


def validate_measurement(body: bytes, *, max_bytes: int) -> Valid | Rejection:
    """Valide un message reçu (octets). Ne lève jamais : tout défaut devient un `Rejection`."""
    if len(body) > max_bytes:
        reason = f"message de plus de {max_bytes} octets (limite de la collecte)"
        return Rejection(
            "UNREADABLE", reason, _text(body), errors=[{"field": "body", "message": reason}]
        )
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        reason = f"ni UTF-8 ni JSON valide (octet illisible à la position {error.start})"
        return Rejection(
            "UNREADABLE", reason, _text(body), errors=[{"field": "body", "message": reason}]
        )
    try:
        raw = json.loads(text, parse_constant=_never)
    except json.JSONDecodeError as error:
        reason = f"JSON illisible à la position {error.pos} : {error.msg}"
        return Rejection(
            "UNREADABLE", reason, _text(body), errors=[{"field": "body", "message": reason}]
        )
    except (ValueError, RecursionError) as error:
        reason = "JSON illisible : constante non permise ou imbrication trop profonde"
        detail = {"field": "body", "message": f"{reason} ({type(error).__name__})"}
        return Rejection("UNREADABLE", reason, _text(body), errors=[detail])
    intersection = _intersection_of(raw)
    key = intersection

    def reject(code: str, reason: str, errors: list[dict[str, str]]) -> Rejection:
        return Rejection(code, _trim(reason), raw, intersection, key, errors)

    if not isinstance(raw, dict):
        message = "un objet JSON est attendu"
        return reject(
            "CONTRACT_VIOLATION", f"(racine) : {message}", [{"field": "body", "message": message}]
        )
    received_type = raw.get("type")
    if isinstance(received_type, str) and received_type != MEASUREMENT_TYPE:
        shown = received_type[:100]
        message = f"type {shown!r} non accepté sur {SOURCE_TOPIC} (attendu : {MEASUREMENT_TYPE})"
        return reject("UNKNOWN_TYPE", message, [{"field": "body.type", "message": message}])
    try:
        model = MeasurementEvent.model_validate(raw)
    except ValidationError as error:
        problems, reason = _contract_errors(error)
        return reject("CONTRACT_VIOLATION", reason, problems)
    rules = semantic_errors(model)
    if rules:
        return reject(
            "SEMANTIC_VIOLATION",
            " ; ".join(rules),
            [{"field": "body", "message": r} for r in rules],
        )
    return Valid(raw, model)
