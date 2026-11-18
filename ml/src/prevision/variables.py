"""Variables des modèles de prévision : le passé de chaque capteur et l'heure, jamais l'avenir ni le capteur lui-même.

Un exemple = un capteur à l'instant `t` ; la réponse est la vitesse à `t + horizon`. Les variables ne regardent que
`t` et le passé. Aucune variable ne dit **quel** capteur c'est (ni sa moyenne, ni son identifiant) : un modèle appris sur
les 207 capteurs de METR-LA doit pouvoir s'appliquer à un capteur qu'il n'a jamais vu, comme ceux du simulateur.

| Variable | Sens |
|---|---|
| `x0`, `lag1` à `lag11` | vitesse à `t` et aux pas précédents (valeur remplie : la dernière mesure connue quand elle manque) |
| `moy3`, `moy12`, `ecart12` | moyenne des 3 et des 12 derniers pas mesurés ; écart type des 12 derniers pas |
| `manque12` | part des 12 derniers pas sans mesure |
| `tod_sin`, `tod_cos` | heure de la journée (sinus et cosinus) |
| `sem_sin`, `sem_cos`, `weekend` | position dans la semaine (sinus et cosinus), samedi ou dimanche |
"""

import numpy as np

from prevision import PAS_MIN

LAGS = (1, 2, 3, 5, 8, 11)
FENETRE = 12
DEBUT_MIN = FENETRE - 1  # premier pas qui a 12 pas de passé
NOMS = ("x0", *(f"lag{k}" for k in LAGS), "moy3", "moy12", "ecart12", "manque12", "tod_sin", "tod_cos", "sem_sin", "sem_cos", "weekend")
JOUR_MS = 86_400_000


def remplir(vitesses: np.ndarray, valeur_initiale: float) -> np.ndarray:
    """Remplit chaque colonne avec sa dernière mesure connue (le passé seulement) ; avant la première : `valeur_initiale`."""
    rempli = vitesses.copy()
    rang = np.where(np.isnan(rempli), 0, np.arange(len(rempli))[:, None])
    np.maximum.accumulate(rang, axis=0, out=rang)
    rempli = np.take_along_axis(rempli, rang, axis=0)
    rempli[np.isnan(rempli)] = valeur_initiale
    return rempli


def _somme_glissante(cumul: np.ndarray, t: np.ndarray, largeur: int) -> np.ndarray:
    return cumul[t + 1] - cumul[t + 1 - largeur]


def variables_temporelles(instants_ms: np.ndarray) -> tuple[np.ndarray, ...]:
    """Heure de la journée, position dans la semaine et week-end, pour des instants en millisecondes (1er janvier 1970 = jeudi)."""
    jour = instants_ms // JOUR_MS
    fraction = (instants_ms % JOUR_MS) / JOUR_MS
    semaine = (((jour + 3) % 7) + fraction) / 7.0
    return (np.sin(2 * np.pi * fraction), np.cos(2 * np.pi * fraction), np.sin(2 * np.pi * semaine), np.cos(2 * np.pi * semaine),
            (((jour + 3) % 7) >= 5).astype(float))


def moyenne_glissante(brut: np.ndarray, rempli: np.ndarray, t: np.ndarray, largeur: int) -> np.ndarray:
    """Moyenne des mesures réelles des `largeur` derniers pas (à `t` inclus) ; `rempli` à `t` quand il n'y en a aucune."""
    present = ~np.isnan(brut)
    cumul_somme = np.vstack([np.zeros((1, brut.shape[1])), np.cumsum(np.nan_to_num(brut), axis=0)])
    cumul_nombre = np.vstack([np.zeros((1, brut.shape[1])), np.cumsum(present, axis=0)])
    somme, nombre = _somme_glissante(cumul_somme, t, largeur), _somme_glissante(cumul_nombre, t, largeur)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(nombre > 0, somme / nombre, rempli[t])


def matrice(brut: np.ndarray, rempli: np.ndarray, instants_ms: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Matrice des variables : une ligne par (pas de `t`, capteur), les capteurs variant le plus vite. Forme (len(t) × capteurs, len(NOMS))."""
    capteurs = brut.shape[1]
    colonnes = [rempli[t]] + [rempli[t - k] for k in LAGS]
    colonnes += [moyenne_glissante(brut, rempli, t, 3), moyenne_glissante(brut, rempli, t, FENETRE)]
    cumul = np.vstack([np.zeros((1, capteurs)), np.cumsum(rempli, axis=0)])
    cumul2 = np.vstack([np.zeros((1, capteurs)), np.cumsum(rempli**2, axis=0)])
    moyenne = _somme_glissante(cumul, t, FENETRE) / FENETRE
    colonnes.append(np.sqrt(np.maximum(_somme_glissante(cumul2, t, FENETRE) / FENETRE - moyenne**2, 0.0)))
    cumul_present = np.vstack([np.zeros((1, capteurs)), np.cumsum(~np.isnan(brut), axis=0)])
    colonnes.append(1.0 - _somme_glissante(cumul_present, t, FENETRE) / FENETRE)
    colonnes += [np.repeat(c[:, None], capteurs, axis=1) for c in variables_temporelles(instants_ms[t])]
    return np.stack([c.reshape(-1) for c in colonnes], axis=1).astype(np.float32)


def reponses(brut: np.ndarray, t: np.ndarray, horizon_pas: int) -> np.ndarray:
    """Vitesse mesurée à `t + horizon` (NaN si elle manque), à plat comme `matrice`."""
    return brut[t + horizon_pas].reshape(-1)


def duree_min(pas: int) -> int:
    return pas * PAS_MIN
