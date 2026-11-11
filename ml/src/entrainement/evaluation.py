"""Du modèle aux quatre mesures du cadrage : prédictions par série, confirmation sur 2 fenêtres, règle de référence."""

from collections import Counter

from entrainement import candidats
from mesures import metriques, reference
from mesures.metriques import ETATS, Mesures
from preparation import ajustement, variables

CONFIRMATION = 2  # fenêtres consécutives : la variante décidée dans le cadrage (section 6), pas un réglage


def bornes(lignes: list[dict]) -> list[tuple[int, int]]:
    """Début et fin (exclue) de chaque série (run, tronçon) dans `lignes`, qui doivent être triées par série puis par temps."""
    resultat, debut = [], 0
    for i in range(1, len(lignes) + 1):
        if i == len(lignes) or (lignes[i]["run_id"], lignes[i]["road_segment_id"]) != (lignes[debut]["run_id"], lignes[debut]["road_segment_id"]):
            resultat.append((debut, i))
            debut = i
    return resultat


def confirmer(predits: list[str], n: int = CONFIRMATION) -> list[str]:
    """L'état annoncé ne change que lorsque le nouvel état est prédit `n` fois de suite.

    La première prédiction de la série est annoncée telle quelle. C'est la stabilité de la règle de l'ADR-028, appliquée
    à la sortie d'un modèle qui, lui, se prononce minute par minute.
    """
    if not predits:
        return []
    annonce, en_attente, compte, sortie = predits[0], None, 0, [predits[0]]
    for etat in predits[1:]:
        if etat == annonce:
            en_attente, compte = None, 0
        else:
            compte = compte + 1 if etat == en_attente else 1
            en_attente = etat
            if compte >= n:
                annonce, en_attente, compte = etat, None, 0
        sortie.append(annonce)
    return sortie


def mesurer_predictions(lignes: list[dict], predits: list[str], confirmation: bool) -> Mesures:
    vrais = [ligne["label_state"] for ligne in lignes]
    series = []
    for debut, fin in bornes(lignes):
        p = predits[debut:fin]
        series.append((vrais[debut:fin], confirmer(p) if confirmation else p))
    return metriques.mesurer(series)


def mesurer_la_regle(lignes: list[dict]) -> Mesures:
    """La règle de seuils de l'ADR-028 sur les mêmes lignes (même code que le traitement en flux)."""
    series: dict[tuple[str, str], list[tuple]] = {}
    for ligne in lignes:
        series.setdefault((ligne["run_id"], ligne["road_segment_id"]), []).append(
            (ligne["run_id"], ligne["road_segment_id"], ligne["window_start"], ligne["vehicle_count"], ligne["speed_ratio"], ligne["label_state"]))
    return reference.mesurer_la_regle(series)


def matrice_de_confusion(vrais: list[str], predits: list[str]) -> dict[str, dict[str, int]]:
    """`matrice[état réel][état annoncé]` : voir quelles confusions coûtent (ralenti pris pour fluide, etc.)."""
    comptes = Counter(zip(vrais, predits, strict=True))
    return {reel: {annonce: comptes[(reel, annonce)] for annonce in ETATS} for reel in ETATS}


def predictions(modele, preparation: ajustement.Preparation, lignes: list[dict], imputer: bool) -> tuple[list[list[float]], list[str]]:
    matrice, _ = preparation.transformer(lignes, imputer=imputer)
    return matrice, [str(etat) for etat in modele.predict(matrice)]


def preparer(entrainement: list[dict], runs_entrainement) -> ajustement.Preparation:
    """La préparation ajustée sur l'entraînement **seul** : un autre run est refusé."""
    return ajustement.Preparation(variables.DETECTION).ajuster(entrainement, runs_permis=set(runs_entrainement))

