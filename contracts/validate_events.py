#!/usr/bin/env python3
"""Valide des événements Novaria Core contre les contrats de contracts/events/ (ADR-012).

Usage (identique sous Linux et Windows ; Windows : `py -3`) :
    python3 contracts/validate_events.py contracts/events/examples/*.json
    python3 contracts/validate_events.py evenement.json autre.json

Dépendances : pip install jsonschema referencing
Code de sortie : 0 si tous les événements sont valides, 1 sinon, 2 si un fichier est illisible.
Le fichier peut contenir un événement (objet) ou une liste d'événements.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

EVENTS_DIR = Path(__file__).resolve().parent / "events"

# type d'événement → fichier de schéma
SCHEMA_BY_TYPE = {
    "novaria.iot.measurement.v1": "iot-measurement.schema.json",
    "novaria.traffic.indicator.v1": "traffic-indicator.schema.json",
    "novaria.alert.state_changed.v1": "alert-event.schema.json",
    "novaria.traffic.recommendation.v1": "traffic-recommendation.schema.json",
    "novaria.signal.status.v1": "signal-status.schema.json",
    "novaria.error.rejected.v1": "error-rejected.schema.json",
}


def _load_registry() -> tuple[Registry, dict[str, dict]]:
    schemas = {}
    registry = Registry()
    for path in sorted(EVENTS_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry, schemas


_REGISTRY, _SCHEMAS = _load_registry()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def schema_errors(event: dict) -> list[str]:
    """Erreurs du schéma JSON (structure, types, bornes, règles conditionnelles)."""
    schema_name = SCHEMA_BY_TYPE.get(event.get("type", ""))
    if schema_name is None:
        return [f"type inconnu : {event.get('type')!r} (attendus : {', '.join(sorted(SCHEMA_BY_TYPE))})"]
    validator = Draft202012Validator(_SCHEMAS[schema_name], registry=_REGISTRY, format_checker=FormatChecker())
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(racine)'} : {e.message}"
            for e in sorted(validator.iter_errors(event), key=lambda e: list(e.absolute_path))]


def _duplicates(values: list[str]) -> list[str]:
    return sorted({v for v in values if values.count(v) > 1})


def _recommendation_errors(event: dict, data: dict) -> list[str]:
    errors = []
    if event["id"] != data["recommendation_id"]:
        errors.append("id d'une recommandation attendu : data.recommendation_id")
    if _parse_utc(data["valid_until"]) <= _parse_utc(event["time"]):
        errors.append("valid_until doit être postérieur à time")
    if sum(phase["duration_s"] for phase in data["phases"]) != data["cycle_s"]:
        errors.append("cycle_s doit être égal à la somme des durées des phases")
    doubles = _duplicates([phase["phase_id"] for phase in data["phases"]])
    if doubles:
        errors.append(f"phase_id en double : {', '.join(doubles)}")
    return errors


def _signal_status_errors(event: dict, data: dict) -> list[str]:
    errors = []
    ids = [phase["phase_id"] for phase in data["phases"]]
    if _duplicates(ids):
        errors.append(f"phase_id en double : {', '.join(_duplicates(ids))}")
    if data["current_phase_id"] not in ids:
        errors.append("current_phase_id doit désigner une phase de phases")
    if _parse_utc(data["phase_started_at"]) > _parse_utc(event["time"]):
        errors.append("phase_started_at ne peut pas être postérieur à time")
    for phase in data["phases"]:
        if phase["duration_s"] < phase["min_duration_s"]:
            errors.append(f"phase {phase['phase_id']} : duration_s inférieur à min_duration_s")
    return errors


def semantic_errors(event: dict) -> list[str]:
    """Règles que le schéma JSON ne sait pas exprimer (comparaison entre champs). Voir le dictionnaire de données."""
    errors: list[str] = []
    data = event.get("data", {})
    if event.get("type") == "novaria.error.rejected.v1":
        # le carrefour d'un message rejeté peut être inconnu : le sujet vaut alors UNKNOWN
        if event.get("subject") != (data.get("intersection_id") or "UNKNOWN"):
            errors.append("subject doit être égal à data.intersection_id, ou à UNKNOWN s'il est null (clé de partition)")
    elif event.get("subject") != data.get("intersection_id"):
        errors.append("subject doit être égal à data.intersection_id (clé de partition)")
    try:
        if event["type"] == "novaria.iot.measurement.v1":
            instant_ms = int(_parse_utc(event["time"]).timestamp() * 1000)
            expected = f"{data['provenance']['run_id']}:{data['sensor_id']}:{instant_ms}"
            if event["id"] != expected:
                errors.append(f"id de mesure attendu : {expected}")
        elif event["type"] == "novaria.traffic.indicator.v1":
            start = _parse_utc(data["window_start"])
            size = data["window_size_s"]
            if int(start.timestamp()) % size != 0:
                errors.append("window_start doit être aligné sur la taille de la fenêtre")
            if _parse_utc(event["time"]) != datetime.fromtimestamp(start.timestamp() + size, timezone.utc):
                errors.append("time d'un indicateur = fin de fenêtre (window_start + window_size_s)")
            if data["sample_count"] > data["expected_sample_count"] * 2:
                errors.append("sample_count dépasse deux fois le nombre attendu (doublons ?)")
        elif event["type"] == "novaria.alert.state_changed.v1":
            if data["resolved_at"] is not None and _parse_utc(data["resolved_at"]) < _parse_utc(data["opened_at"]):
                errors.append("resolved_at ne peut pas précéder opened_at")
        elif event["type"] == "novaria.traffic.recommendation.v1":
            errors.extend(_recommendation_errors(event, data))
        elif event["type"] == "novaria.signal.status.v1":
            errors.extend(_signal_status_errors(event, data))
        elif event["type"] == "novaria.error.rejected.v1":
            if _parse_utc(event["time"]) != _parse_utc(data["rejected_at"]):
                errors.append("time d'un rejet doit être égal à data.rejected_at")
    except (KeyError, TypeError, ValueError):
        pass  # champ absent ou mal typé : déjà signalé par le schéma
    return errors


def validate_event(event: dict) -> list[str]:
    """Rend la liste des erreurs (vide si l'événement est valide)."""
    errors = schema_errors(event)
    return errors if errors else semantic_errors(event)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, help="fichiers JSON (un événement ou une liste)")
    args = parser.parse_args(argv)
    failures = 0
    for path in args.files:
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print(f"[ERREUR] {path} : {error}", file=sys.stderr)
            return 2
        for index, event in enumerate(content if isinstance(content, list) else [content]):
            errors = validate_event(event)
            label = f"{path.name}" + (f"[{index}]" if isinstance(content, list) else "")
            if errors:
                failures += 1
                print(f"[KO] {label}")
                for message in errors:
                    print(f"       - {message}")
            else:
                print(f"[OK] {label}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
