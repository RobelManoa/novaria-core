"""Variables « spatiales » et « habituelles » de la prévision : les capteurs voisins et le profil de la semaine (IA-16).

Le premier modèle d'IA-10 ne regarde que le passé du capteur lui-même. Or une vitesse ne baisse pas toute seule : un
ralentissement naît en amont et se propage. Ce module ajoute trois familles de variables, toutes calculées avec le passé
seulement et avec des statistiques de la **période d'apprentissage** seulement (jamais de la validation ni du test) :

| Famille | Variables | Sens |
|---|---|---|
| Habituel | `hab_t`, `hab_cible`, `ecart_hab`, `dhab` | vitesse habituelle de ce capteur à ce moment de la semaine, à `t` et à `t + h` ; écart de la vitesse actuelle à l'habituel ; variation habituelle attendue |
| Voisins | `v{k}_x0`, `v{k}_d3`, `voisins_moy_d3`, `voisins_min` | vitesse et variation sur 3 pas des K capteurs dont l'écart à l'habituel ressemble le plus à celui du capteur ; moyenne de leurs variations ; leur vitesse minimale |
| Réseau | `reseau_moy`, `reseau_d3`, `reseau_part_lente` | vitesse moyenne de tous les capteurs, sa variation sur 3 pas, part des capteurs sous 60 % de leur habituel |

**Limite assumée.** Ces variables dépendent d'**un réseau** : l'habituel et les voisins se calculent sur l'historique de ce
réseau. Un modèle appris ainsi ne sert que ce réseau (ADR-032, section 3.2), pas un capteur jamais vu. Un capteur sans
historique garde le modèle de base.
"""

from dataclasses import dataclass

import numpy as np

from prevision import PAS_PAR_JOUR
from prevision.variables import JOUR_MS, matrice

NOMS_BASE_HABITUEL = ("hab_t", "hab_cible", "ecart_hab", "dhab")
NOMS_RESEAU = ("reseau_moy", "reseau_d3", "reseau_part_lente")
PAS_PAR_SEMAINE = 7 * PAS_PAR_JOUR


def creneau(instants_ms: np.ndarray) -> np.ndarray:
    """Numéro du pas dans la semaine (0 à 2015, lundi 00:00 = 0), pour des instants en ms (1er janvier 1970 = jeudi)."""
    jour = instants_ms // JOUR_MS
    pas_du_jour = ((instants_ms % JOUR_MS) * PAS_PAR_JOUR // JOUR_MS).astype(np.int64)
    return ((jour + 3) % 7) * PAS_PAR_JOUR + pas_du_jour


@dataclass(frozen=True)
class Profil:
    """Ce que le réseau a appris de son propre passé : vitesse habituelle par créneau de la semaine, et voisins."""

    habituel: np.ndarray  # (2016, capteurs) mph, sur toute la période d'apprentissage
    voisins: np.ndarray  # (capteurs, K) rangs des capteurs les plus proches
    k: int
    # Pour les lignes d'APPRENTISSAGE : l'habituel calculé SANS la semaine de la ligne (sinon la ligne se retrouve dans sa propre
    # moyenne et le modèle apprend une variable plus informative qu'elle ne le sera sur des données jamais vues).
    habituel_hors_semaine: np.ndarray  # (semaines, 2016, capteurs)
    premiere_semaine: int

    def noms(self) -> tuple[str, ...]:
        noms = list(NOMS_BASE_HABITUEL)
        for j in range(self.k):
            noms += [f"v{j}_x0", f"v{j}_d3"]
        noms += ["voisins_moy_d3", "voisins_min", *NOMS_RESEAU]
        return tuple(noms)


def semaine(instants_ms: np.ndarray) -> np.ndarray:
    """Numéro de semaine (le jeudi 1er janvier 1970 ouvre la semaine 0 ; seule la différence compte)."""
    return (instants_ms // JOUR_MS + 3) // 7


def apprendre(rempli: np.ndarray, brut: np.ndarray, instants_ms: np.ndarray, apprentissage: np.ndarray, k: int = 6) -> Profil:
    """Profil de la semaine et voisins, appris sur les pas `apprentissage` seulement."""
    slots = creneau(instants_ms[apprentissage])
    capteurs = brut.shape[1]
    semaines = semaine(instants_ms[apprentissage])
    premiere = int(semaines.min())
    rang = semaines - premiere
    nb_semaines = int(rang.max()) + 1
    mesure = ~np.isnan(brut[apprentissage])
    valeurs = np.where(mesure, brut[apprentissage], 0.0)
    somme_sem = np.zeros((nb_semaines, PAS_PAR_SEMAINE, capteurs))
    nombre_sem = np.zeros((nb_semaines, PAS_PAR_SEMAINE, capteurs))
    np.add.at(somme_sem, (rang, slots), valeurs)
    np.add.at(nombre_sem, (rang, slots), mesure.astype(float))
    somme, nombre = somme_sem.sum(axis=0), nombre_sem.sum(axis=0)
    moyenne_capteur = np.nanmean(brut[apprentissage], axis=0)

    def moyenne(s: np.ndarray, n: np.ndarray) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            m = np.where(n > 0, s / n, np.nan)
        return np.where(np.isnan(m), moyenne_capteur, m)

    habituel = moyenne(somme, nombre)
    hors_semaine = np.stack([moyenne(somme - somme_sem[w], nombre - nombre_sem[w]) for w in range(nb_semaines)]).astype(np.float32)
    # Voisins : les capteurs dont l'écart à l'habituel varie comme le sien (le ralentissement se propage, l'habituel est commun à tous).
    ecart = rempli[apprentissage] - habituel[slots]
    ecart = ecart - ecart.mean(axis=0, keepdims=True)
    norme = np.linalg.norm(ecart, axis=0)
    norme[norme == 0] = 1.0
    correlation = (ecart.T @ ecart) / np.outer(norme, norme)
    np.fill_diagonal(correlation, -np.inf)
    voisins = np.argsort(-correlation, axis=1)[:, :k]
    return Profil(habituel.astype(np.float32), voisins, k, hors_semaine, premiere)


def variables(profil: Profil, rempli: np.ndarray, instants_ms: np.ndarray, t: np.ndarray, horizon_pas: int, en_apprentissage: bool = False) -> np.ndarray:
    """Colonnes supplémentaires, une ligne par (pas de `t`, capteur), dans l'ordre de `Profil.noms()`.

    `en_apprentissage` : les pas `t` sont ceux qui servent à apprendre ; l'habituel est alors celui des autres semaines.
    """
    capteurs = rempli.shape[1]
    x0 = rempli[t]
    slot_t = creneau(instants_ms[t])
    slot_cible = (slot_t + horizon_pas) % PAS_PAR_SEMAINE
    if en_apprentissage:
        rang = semaine(instants_ms[t]) - profil.premiere_semaine
        hab_t, hab_cible = profil.habituel_hors_semaine[rang, slot_t], profil.habituel_hors_semaine[rang, slot_cible]
    else:
        hab_t, hab_cible = profil.habituel[slot_t], profil.habituel[slot_cible]
    colonnes = [hab_t, hab_cible, x0 - hab_t, hab_cible - hab_t]
    d3 = x0 - rempli[t - 3]
    voisins_x0 = x0[:, profil.voisins]  # (pas, capteurs, k)
    voisins_d3 = d3[:, profil.voisins]
    for j in range(profil.k):
        colonnes += [voisins_x0[:, :, j], voisins_d3[:, :, j]]
    colonnes += [voisins_d3.mean(axis=2), voisins_x0.min(axis=2)]
    reseau = x0.mean(axis=1, keepdims=True)
    colonnes += [np.repeat(reseau, capteurs, axis=1), np.repeat(d3.mean(axis=1, keepdims=True), capteurs, axis=1),
                 np.repeat(((x0 < 0.6 * hab_t).mean(axis=1, keepdims=True)), capteurs, axis=1)]
    return np.stack([c.reshape(-1) for c in colonnes], axis=1).astype(np.float32)


def matrice_etendue(profil: Profil, brut: np.ndarray, rempli: np.ndarray, instants_ms: np.ndarray, t: np.ndarray, horizon_pas: int,
                    en_apprentissage: bool = False) -> np.ndarray:
    """Les variables d'IA-10 suivies des variables habituelles, voisines et de réseau."""
    return np.hstack([matrice(brut, rempli, instants_ms, t), variables(profil, rempli, instants_ms, t, horizon_pas, en_apprentissage)])
