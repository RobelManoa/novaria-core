#!/usr/bin/env python3
"""Crée un service sous services/ à partir du gabarit services/_gabarit (issue MS-04).

Bibliothèque standard uniquement. Le gabarit est un vrai service : il passe lint, tests et build.
Créer un service = copier le dossier et remplacer le mot « gabarit » par le nom du service ; la CI parcourt
`services/*/` et contrôle le nouveau service sans être modifiée.

Utilisation : python scripts/dev/new_service.py alerte      (Windows : py -3 scripts/dev/new_service.py alerte)
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = "_gabarit"
NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
SKIPPED = shutil.ignore_patterns(
    "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "*.pyc", ".coverage", "coverage.xml"
)
TEXT_NAMES = {"Dockerfile", ".dockerignore"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".yml", ".yaml", ".json"}
# « gabarit » est remplacé quand c'est un mot isolé, pas dans « _gabarit » ni dans un chemin « /gabarit ».
WORD = re.compile(r"(?<![\w/])(gabarit|Gabarit)\b")


class NewServiceError(Exception):
    """Erreur attendue, affichée sans trace d'appel."""


def substitute(text: str, name: str) -> str:
    """Remplace « gabarit » par `name` et « Gabarit » par `name` avec une majuscule initiale."""
    return WORD.sub(lambda m: name if m.group(1) == "gabarit" else name[:1].upper() + name[1:], text)


def is_text(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix in TEXT_SUFFIXES


def create(name: str, root: Path = ROOT) -> Path:
    """Copie le gabarit vers services/<name> et renvoie le dossier créé."""
    if not NAME.fullmatch(name):
        raise NewServiceError(
            f"nom invalide : {name!r}. Attendu : minuscules, chiffres et tirets, 2 à 31 caractères, "
            "commençant par une lettre (exemple : alerte, reponse-exterieure)."
        )
    source = root / "services" / TEMPLATE
    target = root / "services" / name
    if not source.is_dir():
        raise NewServiceError(f"gabarit introuvable : {source}")
    if target.exists():
        raise NewServiceError(f"{target.relative_to(root).as_posix()} existe déjà : choisir un autre nom.")
    shutil.copytree(source, target, ignore=SKIPPED)
    for path in sorted(target.rglob("*")):
        if path.is_file() and is_text(path):
            text = path.read_text(encoding="utf-8")
            path.write_text(substitute(text, name), encoding="utf-8", newline="\n")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="nom du service : minuscules, chiffres, tirets (exemple : alerte)")
    args = parser.parse_args(argv)
    try:
        target = create(args.name)
    except NewServiceError as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        return 2
    print(f"Service créé : {target.relative_to(ROOT).as_posix()}")
    print("Étapes suivantes (voir CONTRIBUTING.md, « Créer un nouveau service ») :")
    print(f"  1. cd services/{args.name} puis créer l'environnement et lancer pytest et ruff")
    print("  2. ajouter le service à docker-compose.yml (issue MS-06) et son contrat dans contracts/")
    print("  3. aucune modification de la CI : elle parcourt services/*/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
