"""Lecture des fichiers du jeu v1 en lignes (dictionnaires colonne -> valeur), triées dans l'ordre du temps.

Le fichier de test n'est **pas** lisible par défaut : il sert une seule fois, à l'évaluation finale (cadrage ML,
section 7). L'appelant qui l'ouvre le dit (`evaluation_finale=True`).
"""

from collections import defaultdict
from pathlib import Path

from jeu_entrainement import catalogue, parquet
from jeu_entrainement.simulation import RACINE

DOSSIER_JEU = RACINE / "data" / "datasets" / catalogue.JEU_ID
ENSEMBLES_LISIBLES = (catalogue.TRAIN, catalogue.VALIDATION)


class EnsembleReserve(ValueError):
    """Le test ne se lit qu'à l'évaluation finale."""


def charger(ensemble: str, dossier: Path = DOSSIER_JEU, *, evaluation_finale: bool = False) -> list[dict]:
    """Les lignes d'un ensemble, triées par (run, tronçon, début de fenêtre)."""
    if ensemble not in catalogue.ENSEMBLES:
        raise ValueError(f"ensemble inconnu : {ensemble!r}")
    if ensemble == catalogue.TEST and not evaluation_finale:
        raise EnsembleReserve(
            f"« {ensemble} » est réservé à l'évaluation finale (IA-03) : lisibles ici, {', '.join(ENSEMBLES_LISIBLES)}"
        )
    colonnes, lignes = parquet.lire(dossier / f"{ensemble}.parquet")
    noms = [c.nom for c in colonnes]
    resultat = [dict(zip(noms, ligne, strict=True)) for ligne in lignes]
    resultat.sort(key=lambda ligne: (ligne["run_id"], ligne["road_segment_id"], ligne["window_start"]))
    return resultat


def par_serie(lignes: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Les lignes regroupées par (run, tronçon), chaque série dans l'ordre du temps."""
    series: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for ligne in lignes:
        series[(ligne["run_id"], ligne["road_segment_id"])].append(ligne)
    for serie in series.values():
        serie.sort(key=lambda ligne: ligne["window_start"])
    return dict(series)


def minute(ligne: dict) -> int:
    """Le début de la fenêtre en minutes depuis 1970 (la clé des séries de `historique.py`)."""
    return int(ligne["window_start"].timestamp() // 60)
