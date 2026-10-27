#!/usr/bin/env python3
"""Conformité des messages du bus, par service et par sujet (MS-03, ADR-012).

Chaque service ne publie que sur les sujets dont il est producteur, ne consomme que ceux dont il est consommateur,
et chaque message doit respecter le contrat du sujet : type attendu, schéma JSON, règles entre champs.
`contracts/topics.json` est la matrice (sujet, type, schéma, producteurs, consommateurs).

Dans le test d'un service :

    from conformance import assert_publication, assert_consumption
    assert_publication("traitement", "traffic.indicators", message)   # lève ContractViolation sinon

Usage en ligne de commande (identique sous Linux et Windows ; Windows : `py -3`) :
    python3 contracts/conformance.py            # contrôle les exemples de chaque service, code 1 si un écart
    python3 contracts/conformance.py --matrix   # affiche la matrice service x sujet

Dépendances : pip install jsonschema referencing
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import validate_events

ROOT = Path(__file__).resolve().parent
TOPICS_FILE = ROOT / "topics.json"
EXAMPLES = ROOT / "events" / "examples"


class ContractViolation(AssertionError):
    """Un message ou un droit de publication ou de consommation ne respecte pas le contrat."""


def load_registry() -> dict:
    return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))


def services() -> dict[str, dict[str, list[str]]]:
    """{service: {"publishes": [sujets], "consumes": [sujets]}}, déduit de la matrice."""
    registry = load_registry()
    result = {name: {"publishes": [], "consumes": []} for name in registry["services"]}
    for topic, entry in registry["topics"].items():
        for name in entry["producers"]:
            result[name]["publishes"].append(topic)
        for name in entry["consumers"]:
            result[name]["consumes"].append(topic)
    return result


def message_errors(topic: str, message: object) -> list[str]:
    """Erreurs d'un message au regard du contrat du sujet (liste vide si conforme)."""
    entry = load_registry()["topics"].get(topic)
    if entry is None:
        return [f"sujet inconnu : {topic!r} (attendus : {', '.join(load_registry()['topics'])})"]
    if not isinstance(message, dict):
        return ["le message doit être un objet JSON"]
    if message.get("type") != entry["type"]:
        return [f"type {message.get('type')!r} refusé sur {topic} (attendu : {entry['type']})"]
    return validate_events.validate_event(message)


def _rights_errors(service: str, topic: str, role: str) -> list[str]:
    registry = load_registry()
    if service not in registry["services"]:
        return [f"service inconnu : {service!r} (attendus : {', '.join(registry['services'])})"]
    entry = registry["topics"].get(topic)
    if entry is None:
        return [f"sujet inconnu : {topic!r}"]
    key, verb = ("producers", "publier sur") if role == "publish" else ("consumers", "consommer")
    if service not in entry[key]:
        return [f"le service {service} n'a pas le droit de {verb} {topic} (autorisés : {', '.join(entry[key]) or 'aucun'})"]
    return []


def publication_errors(service: str, topic: str, message: object) -> list[str]:
    errors = _rights_errors(service, topic, "publish") or message_errors(topic, message)
    entry = load_registry()["topics"].get(topic)
    if not errors and entry["source"] == "publisher" and message.get("source") != service:
        errors = [f"source {message.get('source')!r} : un message de {topic} est signé par le service qui le publie ({service})"]
    return errors


def consumption_errors(service: str, topic: str, message: object) -> list[str]:
    return _rights_errors(service, topic, "consume") or message_errors(topic, message)


def assert_publication(service: str, topic: str, message: object) -> None:
    errors = publication_errors(service, topic, message)
    if errors:
        raise ContractViolation(f"{service} publie sur {topic} un message hors contrat : " + " ; ".join(errors))


def assert_consumption(service: str, topic: str, message: object) -> None:
    errors = consumption_errors(service, topic, message)
    if errors:
        raise ContractViolation(f"{service} consomme sur {topic} un message hors contrat : " + " ; ".join(errors))


def examples_by_topic() -> dict[str, list[tuple[str, dict]]]:
    """Exemples valides du dossier events/examples, rangés par sujet d'après leur type."""
    topic_of_type = {entry["type"]: topic for topic, entry in load_registry()["topics"].items()}
    result: dict[str, list[tuple[str, dict]]] = {topic: [] for topic in load_registry()["topics"]}
    for path in sorted(EXAMPLES.glob("*.json")):
        event = json.loads(path.read_text(encoding="utf-8"))
        result[topic_of_type[event["type"]]].append((path.name, event))
    return result


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matrix", action="store_true", help="affiche la matrice service x sujet sans rien contrôler")
    args = parser.parse_args(argv)
    matrix = services()
    if args.matrix:
        for name, rights in matrix.items():
            print(f"{name:<10} publie : {', '.join(rights['publishes']) or '-'}  |  consomme : {', '.join(rights['consumes']) or '-'}")
        return 0
    examples = examples_by_topic()
    failures = 0
    for name, rights in matrix.items():
        for role, topics, check in (("publie", rights["publishes"], publication_errors),
                                    ("consomme", rights["consumes"], consumption_errors)):
            for topic in topics:
                own = [(f, e) for f, e in examples[topic]
                       if role == "consomme" or load_registry()["topics"][topic]["source"] == "origin" or e["source"] == name]
                for file_name, event in own:
                    errors = check(name, topic, event)
                    failures += 1 if errors else 0
                    print(f"[{'KO' if errors else 'OK'}] {name} {role} {topic} : {file_name}")
                    for message in errors:
                        print(f"       - {message}")
                if not own:
                    failures += 1
                    print(f"[KO] {name} {role} {topic} : aucun exemple")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
