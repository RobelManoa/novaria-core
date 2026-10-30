"""Empaquette la logique ETL en une archive reproductible : `dist/novaria-etl-<version>.zip` (DAT-06).

    python data/etl/pipelines/empaqueter.py

L'archive contient les paquets `pipelines` et `transforms`, `requirements.txt` et un `MANIFEST.txt` (SHA-256 de chaque
fichier). Elle est écrite dans `dist/` à la racine du dépôt. Elle est déterministe : mêmes sources, même octets, même empreinte
(ordre fixe, dates fixes, pas de cache Python).
C'est la forme que prend le code pour un job AWS Glue (`--extra-py-files`, docs/03-donnees/etl-planifie-local.md),
et pour un déploiement local sans copier le dépôt. Bibliothèque standard seulement.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tomllib
import zipfile
from pathlib import Path

RACINE_ETL = Path(__file__).resolve().parents[1]
PAQUETS = ("pipelines", "transforms")
FICHIERS = ("requirements.txt",)
DATE_FIXE = (1980, 1, 1, 0, 0, 0)  # plus ancienne date qu'une archive zip sache représenter
MANIFESTE = "MANIFEST.txt"
SORTIE = RACINE_ETL.parents[1] / "dist"  # à la racine du dépôt, dossier ignoré par git


def version(racine: Path = RACINE_ETL) -> str:
    return tomllib.loads((racine / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def fichiers_a_empaqueter(racine: Path = RACINE_ETL) -> list[Path]:
    """Chemins relatifs, triés : les sources des paquets (sans cache ni test) et les fichiers listés dans FICHIERS."""
    retenus = [chemin.relative_to(racine) for paquet in PAQUETS for chemin in (racine / paquet).rglob("*.py")]
    retenus += [Path(nom) for nom in FICHIERS]
    return sorted(retenus, key=lambda chemin: chemin.as_posix())


def construire(racine: Path = RACINE_ETL, sortie: Path = SORTIE) -> Path:
    contenus = {chemin.as_posix(): (racine / chemin).read_bytes() for chemin in fichiers_a_empaqueter(racine)}
    manifeste = "".join(f"{hashlib.sha256(octets).hexdigest()}  {nom}\n" for nom, octets in contenus.items())
    sortie.mkdir(parents=True, exist_ok=True)
    archive = sortie / f"novaria-etl-{version(racine)}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zip_:
        for nom, octets in {**contenus, MANIFESTE: manifeste.encode("utf-8")}.items():
            entree = zipfile.ZipInfo(nom, DATE_FIXE)
            entree.compress_type = zipfile.ZIP_DEFLATED
            entree.external_attr = 0o644 << 16
            zip_.writestr(entree, octets)
    return archive


def empreinte(archive: Path) -> str:
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def principal(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Empaquette la logique ETL (pipelines, transforms) en une archive reproductible.")
    parseur.parse_args(argv)
    archive = construire(sortie=SORTIE)
    with zipfile.ZipFile(archive) as zip_:
        nombre = len(zip_.namelist())
    print(f"{archive} : {nombre} fichiers, sha256 {empreinte(archive)}")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
