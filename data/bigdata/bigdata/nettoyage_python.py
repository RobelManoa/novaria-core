"""L'ETL Python de référence : le pipeline de nettoyage de Paris (DAT-04) appliqué aux fichiers du jeu, sans le modifier.

`pipelines.nettoyer_paris.nettoyer_fichier` est **le code de production** : vérification de l'empreinte et de la forme du
fichier, nettoyage ligne à ligne par `transforms.paris_qualite.Nettoyeur`, écriture des lignes propres (CSV) et des
rejets (JSONL). Deux façons de le lancer :

  - `sequentiel` : un fichier après l'autre, un seul processus (c'est ainsi que `lot.py` l'appelle) ;
  - `parallele`  : un processus par fichier à la fois (`multiprocessing`). Les doublons ne se cherchent que dans un
    fichier (DAT-04) : les fichiers sont indépendants, ce traitement se répartit sans rien changer au résultat.

La seconde est la comparaison honnête pour Spark : sur une machine à N cœurs, Spark local en emploie N, et Python aussi.
Bibliothèque standard seulement (le code importé l'est aussi).
"""

import multiprocessing
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "data" / "etl"))

from pipelines import nettoyer_paris  # noqa: E402


def nettoyer_un(chemin: Path, maintenant: datetime) -> dict:
    """Nettoie un fichier avec le pipeline de production ; rend son bilan (même forme que `Bilan.en_dict`)."""
    resultat = nettoyer_paris.nettoyer_fichier(chemin, maintenant=lambda: maintenant)
    return resultat.bilan.en_dict()


def _travail(arguments: tuple[Path, datetime]) -> dict:
    return nettoyer_un(*arguments)


def additionner(bilans: Sequence[dict]) -> dict:
    """Le bilan de plusieurs fichiers : les compteurs s'additionnent."""
    total = {"rows_read": 0, "rows_clean": 0, "rows_rejected": 0}
    par_regle, drapeaux = Counter(), Counter()
    for bilan in bilans:
        for cle in total:
            total[cle] += bilan[cle]
        par_regle.update(bilan["by_rule"])
        drapeaux.update(bilan["flags"])
    total["by_rule"] = dict(sorted(par_regle.items()))
    total["flags"] = dict(sorted(drapeaux.items()))
    return total


def sequentiel(fichiers: Sequence[Path], maintenant: datetime) -> dict:
    return additionner([nettoyer_un(chemin, maintenant) for chemin in fichiers])


def parallele(fichiers: Sequence[Path], maintenant: datetime, processus: int) -> dict:
    if processus < 1:
        raise ValueError("au moins un processus")
    with multiprocessing.get_context("spawn").Pool(processus) as groupe:
        return additionner(list(groupe.imap_unordered(_travail, [(chemin, maintenant) for chemin in fichiers])))
