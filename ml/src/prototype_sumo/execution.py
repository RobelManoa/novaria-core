"""SUMO dans Docker : construire l'image, puis `netconvert` et `sumo` dans un conteneur jetable.

Le dossier du run est monté sur `/work` ; le conteneur n'a aucun accès réseau utile et ne garde rien. Sous Linux le conteneur
tourne avec l'identifiant de l'utilisateur (sinon il ne pourrait pas écrire dans le dossier monté) ; Docker Desktop (Windows)
gère les droits lui-même.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from jeu_entrainement.simulation import RACINE
from prototype_sumo import IMAGE

CONTEXTE = RACINE / "ml" / "sumo"
COMMANDE = ("netconvert --node-files nodes.nod.xml --edge-files edges.edg.xml -o net.net.xml --tls.layout opposites --no-turnarounds true --no-warnings true"
            " && sumo -c run.sumocfg")


class DockerAbsent(Exception):
    """Docker ne répond pas ou l'image manque : le message dit quoi faire."""


def _docker(*arguments: str, **options) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["docker", *arguments], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, **options)
    except FileNotFoundError as erreur:
        raise DockerAbsent("docker est introuvable : installer Docker (docs/08-exploitation/poste-de-travail.md)") from erreur


def image_presente() -> bool:
    return _docker("image", "inspect", IMAGE).returncode == 0


def construire_image() -> None:
    """`docker build` du dossier `ml/sumo` (environ 2 minutes la première fois : SUMO fait 90 Mo à télécharger, l'image 1,2 Go décompressée)."""
    sortie = _docker("build", "-t", IMAGE, str(CONTEXTE))
    if sortie.returncode:
        raise DockerAbsent(f"la construction de l'image a échoué : {sortie.stderr.strip()[-300:]}")


def dossier_temporaire(prefixe: str) -> tempfile.TemporaryDirectory:
    """Dossier jetable sous `var/` (monté dans le conteneur). `var/` est ignoré par Git : il n'existe pas sur un poste neuf ni
    dans la CI, on le crée au besoin."""
    parent = RACINE / "var"
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefixe, dir=parent)


def utilisateur() -> list[str]:
    return ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []


def lancer(dossier: Path, delai_s: int = 900) -> str:
    """Construit le réseau puis simule ; rend la sortie de SUMO. Lève `DockerAbsent` si l'image manque, `RuntimeError` si SUMO échoue."""
    if not image_presente():
        raise DockerAbsent(f"l'image {IMAGE} est absente : python3 scripts/dev/dev.py ml-sumo image (Windows : py -3 ...)")
    sortie = _docker("run", "--rm", *utilisateur(), "-v", f"{dossier.resolve()}:/work", IMAGE, "sh", "-c", COMMANDE, timeout=delai_s)
    if sortie.returncode:
        raise RuntimeError(f"SUMO a échoué (code {sortie.returncode}) : {(sortie.stdout + sortie.stderr).strip()[-600:]}")
    return sortie.stdout


if __name__ == "__main__":
    print(IMAGE, "présente" if image_presente() else "absente", file=sys.stderr)
