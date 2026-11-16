"""Commandes Docker du prototype Big Data (DAT-08) : construire l'image, lancer le prototype ou ses tests.

La logique est ici (testable sans Docker) ; `dev.py bigdata-build`, `bigdata` et `bigdata-test` ne font que l'appeler.
Le dépôt est monté en **lecture seule** (le code n'est pas dans l'image) ; les données et les sorties sont dans un volume
Docker, hors du dépôt : rien n'est écrit dans le dossier du projet. Mêmes commandes sous Linux et sous Windows.
"""

from __future__ import annotations

from pathlib import Path

IMAGE = "novaria-bigdata"
VOLUME = "novaria-bigdata"  # fichiers bruts générés, sorties des moteurs, fichiers temporaires de Spark
DOCKERFILE = Path("data") / "bigdata" / "Dockerfile"
CPUS_PAR_DEFAUT = "4"
MEMOIRE_PAR_DEFAUT = "6g"
DEPOT_DANS_L_IMAGE = "/repo"
DOSSIER_DE_TRAVAIL = f"{DEPOT_DANS_L_IMAGE}/data/bigdata"


def commande_de_construction(racine: Path) -> list[str]:
    """`docker build` : le contexte est le dossier du prototype (il ne contient que les dépendances épinglées)."""
    contexte = Path(racine) / "data" / "bigdata"
    return ["docker", "build", "-t", IMAGE, "-f", str(Path(racine) / DOCKERFILE), str(contexte)]


def _base(racine: Path, cpus: str, memoire: str, entrypoint: str | None) -> list[str]:
    commande = ["docker", "run", "--rm", "--cpus", cpus, "--memory", memoire]
    if entrypoint:
        commande += ["--entrypoint", entrypoint, "--workdir", DOSSIER_DE_TRAVAIL]
    commande += ["-v", f"{racine}:{DEPOT_DANS_L_IMAGE}:ro", "-v", f"{VOLUME}:/data", IMAGE]
    return commande


def commande_de_lancement(racine: Path, arguments: list[str], cpus: str = CPUS_PAR_DEFAUT, memoire: str = MEMOIRE_PAR_DEFAUT) -> list[str]:
    """`docker run` du prototype : `arguments` sont ceux de `python -m bigdata` (generer, nettoyer, verifier, mesurer)."""
    return [*_base(racine, cpus, memoire, None), *arguments]


def commande_de_test(racine: Path, cpus: str = CPUS_PAR_DEFAUT, memoire: str = MEMOIRE_PAR_DEFAUT) -> list[str]:
    """Les tests du prototype, dans l'image : PySpark et Java y sont, les tests PySpark ne sont donc pas ignorés."""
    return [*_base(racine, cpus, memoire, "python"), "-m", "unittest", "discover", "-s", "tests", "-t", "."]
