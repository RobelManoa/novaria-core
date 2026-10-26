#!/usr/bin/env python3
"""Contrôle de compatibilité ascendante des schémas d'événements (MS-03, README des contrats).

Compatible = **le nouveau schéma accepte tout message que l'ancien acceptait**. Une rupture exige un nouveau type
(`.v2`) et non une nouvelle version mineure. Le contrôle compare deux états des fichiers de `contracts/events/*.schema.json`.

Usage (identique sous Linux et Windows ; Windows : `py -3`) :
    python3 contracts/check_compat.py --against origin/main     # compare à une révision Git
    python3 contracts/check_compat.py --old dossier-ancien      # compare à un dossier de schémas

Deux niveaux : une **rupture** (code de sortie 1) est démontrée par la comparaison ; un point **à vérifier** (affiché,
code 0, ou 1 avec --strict) est un `pattern`, un `format` ou une `$ref` modifiés, qu'on ne sait pas comparer : un humain
tranche, en relecture de la pull request. Bibliothèque standard seulement.

Limite : comparaison structurelle, sans résoudre les `$ref`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

EVENTS = Path(__file__).resolve().parent / "events"
REPOSITORY = EVENTS.parents[1]
MIN_KEYWORDS = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
MAX_KEYWORDS = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")
OPAQUE_KEYWORDS = ("pattern", "format", "$ref")  # impossibles à comparer : tout changement est une rupture
RESTRICTION_KEYWORDS = ("allOf", "anyOf", "oneOf", "not", "if", "then", "else", "contains", "propertyNames")


def _types(node: dict) -> set[str] | None:
    value = node.get("type")
    if value is None:
        return None
    return set(value) if isinstance(value, list) else {value}


def _values(node: dict) -> list | None:
    if "const" in node:
        return [node["const"]]
    return node.get("enum")


def breaking_changes(old: object, new: object, path: str = "") -> list[str]:
    """Ruptures de compatibilité entre deux nœuds de schéma (liste vide si le nouveau accepte tout l'ancien)."""
    where = path or "(racine)"
    if isinstance(old, bool) or isinstance(new, bool):
        return [] if new is True or old is new else [f"{where} : le schéma passe de {old!r} à {new!r}"]
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    found: list[str] = []

    old_types, new_types = _types(old), _types(new)
    if old_types is not None and (new_types is None or not old_types <= new_types):
        if new_types is not None:
            found.append(f"{where} : type restreint de {sorted(old_types)} à {sorted(new_types)}")

    old_values, new_values = _values(old), _values(new)
    if old_values is not None:
        if new_values is None:
            pass  # contrainte supprimée : élargissement
        else:
            removed = [v for v in old_values if v not in new_values]
            if removed:
                found.append(f"{where} : valeurs retirées {removed}")
    elif new_values is not None:
        found.append(f"{where} : valeurs désormais limitées à {new_values}")

    for keyword in MIN_KEYWORDS:
        if keyword in new and keyword in old and new[keyword] > old[keyword]:
            found.append(f"{where} : {keyword} relevé de {old[keyword]} à {new[keyword]}")
        elif keyword in new and keyword not in old:
            found.append(f"{where} : {keyword} ajouté ({new[keyword]})")
    for keyword in MAX_KEYWORDS:
        if keyword in new and keyword in old and new[keyword] < old[keyword]:
            found.append(f"{where} : {keyword} abaissé de {old[keyword]} à {new[keyword]}")
        elif keyword in new and keyword not in old:
            found.append(f"{where} : {keyword} ajouté ({new[keyword]})")
    if new.get("uniqueItems") is True and old.get("uniqueItems") is not True:
        found.append(f"{where} : uniqueItems ajouté")
    for keyword in OPAQUE_KEYWORDS:
        if keyword in new and new[keyword] != old.get(keyword):
            label = "référence modifiée" if keyword == "$ref" else f"{keyword} modifié ou ajouté"
            found.append(f"? {where} : {label} ({old.get(keyword)!r} -> {new[keyword]!r})")
    for keyword in RESTRICTION_KEYWORDS:
        if keyword in new and keyword not in old:
            found.append(f"{where} : règle {keyword} ajoutée")
        elif keyword in new and keyword in old and new[keyword] != old[keyword]:
            if isinstance(old[keyword], list) and isinstance(new[keyword], list):
                if len(new[keyword]) > len(old[keyword]) and keyword != "anyOf":
                    found.append(f"{where} : règle {keyword} ajoutée")
                for index, (a, b) in enumerate(zip(old[keyword], new[keyword])):
                    found.extend(breaking_changes(a, b, f"{path}/{keyword}/{index}"))
            else:
                found.extend(breaking_changes(old[keyword], new[keyword], f"{path}/{keyword}"))

    old_required, new_required = set(old.get("required", [])), set(new.get("required", []))
    for name in sorted(new_required - old_required):
        found.append(f"{where} : champ devenu obligatoire : {name}")

    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    for name in old_props:
        if name not in new_props:
            if new.get("additionalProperties", True) is False:
                found.append(f"{where}/properties/{name} : champ retiré (les anciens messages qui le portent seraient refusés)")
        else:
            found.extend(breaking_changes(old_props[name], new_props[name], f"{path}/properties/{name}"))
    if old.get("additionalProperties", True) is not False and new.get("additionalProperties") is False:
        found.append(f"{where} : champs inconnus désormais refusés")
    if isinstance(old.get("additionalProperties"), dict) and isinstance(new.get("additionalProperties"), dict):
        found.extend(breaking_changes(old["additionalProperties"], new["additionalProperties"], f"{path}/additionalProperties"))

    if isinstance(old.get("items"), dict) and isinstance(new.get("items"), dict):
        found.extend(breaking_changes(old["items"], new["items"], f"{path}/items"))
    for key in ("$defs",):
        for name, sub in old.get(key, {}).items():
            if name in new.get(key, {}):
                found.extend(breaking_changes(sub, new[key][name], f"{path}/{key}/{name}"))
            else:
                found.append(f"{path}/{key}/{name} : définition retirée")
    return found


def schema_type(schema: dict) -> str | None:
    """Type d'événement (const de `type`) d'un schéma de sujet ; None pour l'enveloppe et les définitions communes."""
    try:
        return schema["allOf"][1]["properties"]["type"]["const"]
    except (KeyError, IndexError, TypeError):
        return None


def compare(old_schemas: dict[str, dict], new_schemas: dict[str, dict]) -> list[str]:
    """Écarts entre deux jeux de schémas {nom de fichier: schéma} ; ceux qui commencent par « ? » sont à vérifier,
    les autres sont des ruptures. Un schéma nouveau ou à nouveau type n'est pas comparé."""
    found: list[str] = []
    for name, new in sorted(new_schemas.items()):
        old = old_schemas.get(name)
        if old is None:
            continue
        if schema_type(old) != schema_type(new):
            continue  # nouvelle version majeure : les deux versions coexistent (README des contrats)
        found.extend(message[:2] + f"{name} " + message[2:] if message.startswith("? ") else f"{name} {message}"
                     for message in breaking_changes(old, new))
    for name in sorted(set(old_schemas) - set(new_schemas)):
        found.append(f"{name} : schéma supprimé")
    return found


def load_directory(directory: Path) -> dict[str, dict]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.schema.json"))}


def load_revision(revision: str) -> dict[str, dict]:
    listing = subprocess.run(["git", "ls-tree", "--name-only", "--full-tree", f"{revision}:contracts/events/"], capture_output=True,
                             text=True, encoding="utf-8", check=False, cwd=REPOSITORY)
    if listing.returncode != 0:
        raise SystemExit(f"Révision illisible ({revision}) : {listing.stderr.strip()}")
    schemas = {}
    for name in listing.stdout.split():
        if name.endswith(".schema.json"):
            blob = subprocess.run(["git", "show", f"{revision}:contracts/events/{name}"], capture_output=True, text=True,
                                  encoding="utf-8", check=True, cwd=REPOSITORY)
            schemas[name] = json.loads(blob.stdout)
    return schemas


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--against", metavar="REVISION", help="révision Git de référence, par exemple origin/main")
    source.add_argument("--old", metavar="DOSSIER", type=Path, help="dossier de schémas de référence")
    parser.add_argument("--strict", action="store_true", help="les points à vérifier font aussi échouer (code 1)")
    args = parser.parse_args(argv)
    old = load_revision(args.against) if args.against else load_directory(args.old)
    changes = compare(old, load_directory(EVENTS))
    breaks = [m for m in changes if not m.startswith("? ")]
    to_check = [m[2:] for m in changes if m.startswith("? ")]
    if breaks:
        print("Ruptures de compatibilité ascendante :")
        for message in breaks:
            print(f"  - {message}")
        print("Une rupture demande un nouveau type d'événement (.v2), pas une version mineure.")
    if to_check:
        print("À vérifier en relecture (non comparable automatiquement) :")
        for message in to_check:
            print(f"  - {message}")
    if not changes:
        print(f"Compatible : {len(old)} schémas de référence, aucun écart.")
    elif not breaks:
        print("Aucune rupture démontrée.")
    return 1 if breaks or (to_check and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
