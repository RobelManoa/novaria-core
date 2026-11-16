"""Ce qu'il faut pour refaire un résultat : jeu, graine, versions, révision du code (champs de `model_runs`, section 10.6)."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from entrainement import SEED
from jeu_entrainement import integrite
from jeu_entrainement.simulation import RACINE

DOSSIER_EVALUATION = RACINE / "ml" / "evaluation"
SELECTION = DOSSIER_EVALUATION / "selection.json"
RESULTAT_TEST = DOSSIER_EVALUATION / "resultat-test.json"
RAPPORT = DOSSIER_EVALUATION / "resultats.md"


class ControleDeSecurite(RuntimeError):
    """Un contrôle bloquant du cadrage (S1) a échoué : on n'entraîne pas."""


def sha256_fichier(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def exiger_le_jeu_intact(dossier: Path, empreinte_attendue: str | None = None) -> str:
    """S1 : les fichiers du jeu sont ceux du manifeste (et de l'empreinte attendue, si on en a une). Rend l'empreinte du jeu."""
    ecarts = integrite.verifier(dossier, empreinte_attendue)
    if ecarts:
        raise ControleDeSecurite("jeu non conforme (S1) : " + " ; ".join(ecarts))
    return json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))["empreinte_du_jeu"]


def _git(*arguments: str) -> str | None:
    try:
        return subprocess.run(["git", *arguments], cwd=RACINE, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def tracabilite(empreinte_du_jeu: str) -> dict:
    import numpy
    import scipy
    import sklearn

    statut = _git("status", "--porcelain", "--", "ml", "data/datasets")
    return {
        "dataset_id": "novaria-congestion-v1",
        "dataset_sha256": empreinte_du_jeu,
        "seed": SEED,
        "git_sha": _git("rev-parse", "HEAD"),
        "code_modifie_non_commite": None if statut is None else bool(statut),
        "versions": {"python": sys.version.split()[0], "scikit-learn": sklearn.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__},
    }

