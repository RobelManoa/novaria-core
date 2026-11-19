"""Les trois références que un modèle doit battre, calculées avec le passé seulement.

| Référence | Prévision de la vitesse à `t + h` | Ce qu'elle suppose |
|---|---|---|
| `persistance` | la dernière vitesse connue à `t` | rien ne change |
| `moyenne_glissante` | la moyenne des mesures de la dernière heure (12 pas) | le bruit se compense |
| `naif_saisonnier` | la vitesse du **même instant la veille** (`t + h − 1 jour`) | la journée se répète |

Quand une mesure manque, c'est la dernière mesure connue qui la remplace (variables.remplir). Le naïf saisonnier a besoin d'une
journée de passé : il est « non applicable » sur un run simulé de quelques heures.
"""

import numpy as np

from prevision import PAS_PAR_JOUR
from prevision.variables import FENETRE, moyenne_glissante

NOMS = ("persistance", "moyenne_glissante", "naif_saisonnier")


def calculer(brut: np.ndarray, rempli: np.ndarray, t: np.ndarray, horizon_pas: int) -> dict[str, np.ndarray | None]:
    """Prévisions à plat (une ligne par pas de `t` et capteur, comme `variables.matrice`) ; `None` si la référence n'est pas applicable."""
    sortie: dict[str, np.ndarray | None] = {
        "persistance": rempli[t].reshape(-1),
        "moyenne_glissante": moyenne_glissante(brut, rempli, t, FENETRE).reshape(-1),
    }
    veille = t + horizon_pas - PAS_PAR_JOUR
    sortie["naif_saisonnier"] = rempli[veille].reshape(-1) if len(t) and veille.min() >= 0 else None
    return sortie
