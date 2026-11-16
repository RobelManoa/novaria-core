"""Variables décalées et moyennes mobiles d'une série : le **passé** d'une minute, jamais la minute elle-même ni l'avenir.

Une série est un dictionnaire `minute (entier, minutes depuis 1970) -> valeur ou None`. Une minute absente du
dictionnaire (fenêtre jamais reçue) et une valeur `None` (route vide) donnent la même chose : une valeur absente, jamais
une valeur inventée. Ces fonctions ne regardent que les clés strictement inférieures à `minute` : c'est ce que les
tests de non-fuite vérifient en changeant l'avenir de la série.

Ce code recalcule **indépendamment** les colonnes que `jeu_entrainement/lignes.py` a écrites : un écart entre les deux
est un défaut de l'un des deux.
"""

import math
from collections.abc import Mapping

LAGS = (1, 2, 3, 4, 5)
MOYENNES = (5, 15)

Serie = Mapping[int, float | None]


def valeur_decalee(serie: Serie, minute: int, k: int) -> float | None:
    if k < 1:
        raise ValueError("un décalage est d'au moins une minute : k = 0 serait la minute elle-même")
    return serie.get(minute - k)


def moyenne_des_precedentes(serie: Serie, minute: int, n: int) -> float | None:
    """Moyenne des valeurs présentes des `n` minutes précédentes (arrondie à 6 décimales comme le jeu)."""
    if n < 1:
        raise ValueError("une moyenne porte sur au moins une minute")
    valeurs = [v for k in range(1, n + 1) if (v := serie.get(minute - k)) is not None]
    return round(math.fsum(valeurs) / len(valeurs), 6) if valeurs else None


def colonnes_historiques(ratio: Serie, flux: Serie, minute: int) -> dict[str, float | None]:
    """Les 14 colonnes d'historique du dictionnaire de données (section 9), dans l'ordre du jeu."""
    colonnes: dict[str, float | None] = {}
    colonnes.update({f"speed_ratio_lag{k}": valeur_decalee(ratio, minute, k) for k in LAGS})
    colonnes.update({f"flow_lag{k}": valeur_decalee(flux, minute, k) for k in LAGS})
    colonnes.update({f"speed_ratio_ma{n}": moyenne_des_precedentes(ratio, minute, n) for n in MOYENNES})
    colonnes.update({f"flow_ma{n}": moyenne_des_precedentes(flux, minute, n) for n in MOYENNES})
    return colonnes


def valeur_a(serie: Serie, minute: int, horizon: int) -> float | None:
    """La valeur de la série `horizon` minutes plus tard : c'est la **réponse** de la prévision, jamais une variable."""
    if horizon < 1:
        raise ValueError("un horizon est d'au moins une minute")
    return serie.get(minute + horizon)
