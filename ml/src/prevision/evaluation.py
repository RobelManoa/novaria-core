"""MAE, RMSE et biais masqués, et intervalle de confiance par jour pour l'écart entre deux méthodes.

Les métriques (le biais est la moyenne de `prévision − réel`) ne portent que sur les exemples dont la vitesse réelle a été mesurée (une mesure manquante n'est ni une
bonne ni une mauvaise prévision). Unité : miles par heure (mph), celle de METR-LA ; 1 mph = 1,609344 km/h.

Intervalle de confiance : les erreurs d'une même journée ne sont pas indépendantes (même trafic, mêmes incidents). On
rééchantillonne donc des **journées entières** (2 000 tirages, graine 42) et on recalcule la MAE de chaque méthode sur les
mêmes journées tirées : l'intervalle à 95 % de l'écart de MAE tient compte de cette dépendance.
"""

import numpy as np

from prevision import SEED

TIRAGES = 2000


def mae(erreur: np.ndarray) -> float:
    return float(np.mean(np.abs(erreur)))


def rmse(erreur: np.ndarray) -> float:
    return float(np.sqrt(np.mean(erreur**2)))


def metriques(prevision: np.ndarray, reel: np.ndarray) -> dict[str, float]:
    masque = ~np.isnan(reel)
    erreur = prevision[masque] - reel[masque]
    return {"mae": mae(erreur), "rmse": rmse(erreur), "biais": float(np.mean(erreur)), "n": int(masque.sum())}


def somme_par_jour(prevision: np.ndarray, reel: np.ndarray, jour: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Somme des erreurs absolues et nombre d'exemples mesurés, pour chaque journée distincte de `jour` (même longueur que `reel`)."""
    masque = ~np.isnan(reel)
    _, rang = np.unique(jour[masque], return_inverse=True)
    erreurs = np.abs(prevision[masque] - reel[masque])
    return np.bincount(rang, weights=erreurs), np.bincount(rang).astype(float)


def ecart_de_mae(somme_a: np.ndarray, somme_b: np.ndarray, nombre: np.ndarray, tirages: int = TIRAGES, graine: int = SEED) -> dict[str, float]:
    """Écart `MAE(a) − MAE(b)` et son intervalle à 95 % par rééchantillonnage de journées. Négatif : `a` fait mieux que `b`."""
    rng = np.random.default_rng(graine)
    jours = len(nombre)
    tirage = rng.integers(0, jours, size=(tirages, jours))
    ecarts = (somme_a[tirage].sum(axis=1) - somme_b[tirage].sum(axis=1)) / nombre[tirage].sum(axis=1)
    point = (somme_a.sum() - somme_b.sum()) / nombre.sum()
    bas, haut = np.percentile(ecarts, [2.5, 97.5])
    return {"ecart_mae": float(point), "bas": float(bas), "haut": float(haut), "jours": int(jours)}
