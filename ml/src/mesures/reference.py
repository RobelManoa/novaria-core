"""Règle de seuils avec hystérésis (ADR-028) rejouée sur le jeu v1 : la référence à battre.

La règle est celle du traitement en flux (`services/traitement/app/flux/classifier.py`), pas une copie : ce que la
production calcule est ce qu'on mesure. Le jeu ne contient pas la complétude des fenêtres : la règle est rejouée avec
une complétude de 1, donc sans état `UNKNOWN` ; un capteur muet donne une fenêtre vide, comptée comme fluide.

Le fichier `test.parquet` n'est **pas** lisible ici : l'ensemble de test sert une seule fois, à l'évaluation finale
(IA-03), après que le seuil d'acceptation est fixé.
"""

import dataclasses
from collections import defaultdict
from pathlib import Path

from jeu_entrainement import catalogue, parquet
from jeu_entrainement.fenetres import importer_le_moteur
from jeu_entrainement.simulation import RACINE
from stockage import ouvrir_magasin_de_jeu
from mesures.metriques import Mesures, mesurer
from preparation.donnees import EnsembleReserve  # noqa: F401 : la même exception pour tous les lecteurs du jeu

DOSSIER_JEU = RACINE / "data" / "datasets" / catalogue.JEU_ID
ENSEMBLES_LISIBLES = ("train", "validation")
COLONNES = ("run_id", "road_segment_id", "window_start", "vehicle_count", "speed_ratio", "label_state")

# Une variation à la fois autour des valeurs de l'ADR-028 : (réglage, valeurs essayées).
VARIATIONS = (
    ("slow_below", (0.50, 0.55, 0.65)),
    ("congested_below", (0.30, 0.40)),
    ("free_above", (0.65, 0.75, 0.80)),
    ("recover_to_slow_above", (0.40, 0.50)),
    ("degrade_windows", (1, 3)),
    ("recover_windows", (2, 4, 5)),
)


def importer_la_regle():
    """Le classificateur et les seuils du traitement en flux (ajoute `services/traitement` au chemin d'import)."""
    importer_le_moteur()
    from app.flux.classifier import Hysteresis, Observation, advance
    from app.flux.rules import DEFAULT_THRESHOLDS, Thresholds

    return Hysteresis, Observation, advance, DEFAULT_THRESHOLDS, Thresholds


def charger(ensemble: str, dossier: Path = DOSSIER_JEU) -> dict[tuple[str, str], list[tuple]]:
    """Les lignes d'un ensemble, par série (run, tronçon), dans l'ordre du temps."""
    if ensemble not in ENSEMBLES_LISIBLES:
        raise EnsembleReserve(
            f"« {ensemble} » est réservé à l'évaluation finale (IA-03) : lisibles ici, {', '.join(ENSEMBLES_LISIBLES)}"
        )
    colonnes, lignes = parquet.decoder(ouvrir_magasin_de_jeu(dossier).get(f"{ensemble}.parquet"))
    noms = [c.nom for c in colonnes]
    positions = [noms.index(nom) for nom in COLONNES]
    series: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for ligne in lignes:
        valeurs = tuple(ligne[p] for p in positions)
        series[(valeurs[0], valeurs[1])].append(valeurs)
    for serie in series.values():
        serie.sort(key=lambda valeurs: valeurs[2])
    return series


def etats_de_la_regle(serie: list[tuple], seuils=None) -> list[str]:
    """L'état annoncé par la règle à chaque minute de la série."""
    hysteresis, observation, advance, par_defaut, _ = importer_la_regle()
    seuils = seuils or par_defaut
    etat, annonces = hysteresis(), []
    for _, _, debut, vehicules, ratio, _ in serie:
        etat = advance(etat, observation(debut, 1.0, ratio, vehicules or 0), seuils)
        annonces.append("FREE_FLOW" if etat.state == "UNKNOWN" else etat.state)
    return annonces


def mesurer_la_regle(series: dict[tuple[str, str], list[tuple]], seuils=None) -> Mesures:
    return mesurer(([ligne[5] for ligne in serie], etats_de_la_regle(serie, seuils)) for serie in series.values())


def sensibilite(series: dict[tuple[str, str], list[tuple]]) -> list[tuple[str, Mesures]]:
    """La règle avec ses valeurs de départ, puis avec chaque variation isolée."""
    *_, par_defaut, _ = importer_la_regle()
    lignes = [("valeurs de l'ADR-028", mesurer_la_regle(series, par_defaut))]
    for reglage, valeurs in VARIATIONS:
        for valeur in valeurs:
            seuils = dataclasses.replace(par_defaut, **{reglage: valeur})
            lignes.append((f"{reglage} = {valeur}", mesurer_la_regle(series, seuils)))
    return lignes


def etat_unique(series: dict[tuple[str, str], list[tuple]]) -> Mesures:
    """Plancher : annoncer `FREE_FLOW` partout (l'état de 89 % des minutes)."""
    return mesurer(([ligne[5] for ligne in serie], ["FREE_FLOW"] * len(serie)) for serie in series.values())


def sans_hysteresis(series: dict[tuple[str, str], list[tuple]]) -> Mesures:
    """Seuils de l'ADR-028 appliqués à chaque minute, sans durée minimale : la même règle sans sa stabilité."""
    *_, par_defaut, _ = importer_la_regle()
    seuils = dataclasses.replace(par_defaut, degrade_windows=1, recover_windows=1)
    return mesurer_la_regle(series, seuils)


def reunir(*ensembles: dict) -> dict:
    """Plusieurs ensembles en un (les clés (run, tronçon) ne se recoupent pas : un run est dans un seul ensemble)."""
    resultat: dict = {}
    for ensemble in ensembles:
        recoupees = resultat.keys() & ensemble.keys()
        if recoupees:
            raise ValueError(f"série présente dans deux ensembles : {sorted(recoupees)[0]}")
        resultat.update(ensemble)
    return resultat
