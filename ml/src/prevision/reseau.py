"""Réseau spatio-temporel de prévision de vitesse (IA-16) : un graphe de capteurs, un GRU par capteur, six horizons d'un coup.

Entrée à l'instant `t` : pour chacun des N capteurs, les 12 derniers pas (vitesse centrée réduite, mesure absente ou non, vitesse
habituelle du créneau), et pour la tête de prévision l'habituel des 6 pas à venir et l'heure. Le graphe est celui des **voisins appris sur
l'apprentissage** (`voisins.apprendre`) : un capteur reçoit la moyenne de ses voisins avant et après le GRU, comme un réseau à graphe très
simple. Sortie : l'écart à la persistance (vitesse(t+h) − vitesse(t)) pour h = 1 à 6 pas (5 à 30 minutes), tous capteurs à la fois.

Le modèle est petit (quelques dizaines de milliers de poids) : il s'entraîne sur processeur en quelques minutes, et son passage avant se
réécrit en numpy seul (`reseau_numpy.py`) pour le service, qui n'a pas PyTorch.
"""

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from prevision import variables, voisins

FENETRE = 12
HORIZONS = 6
ECHELLE_SORTIE = 10.0  # mph : l'écart à la persistance est appris en dizaines de mph
CARACTERISTIQUES = 3  # vitesse, mesure présente, habituel
CONTEXTE = HORIZONS + 4  # habituel futur moins vitesse actuelle, heure (sin, cos), semaine (sin, cos)


def adjacence(profil: voisins.Profil) -> np.ndarray:
    """Matrice (N, N) normalisée par ligne : le capteur lui-même et ses voisins (relation symétrisée)."""
    n = profil.voisins.shape[0]
    a = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        a[i, profil.voisins[i]] = 1.0
    a = np.maximum(a, a.T)
    np.fill_diagonal(a, 1.0)
    return a / a.sum(axis=1, keepdims=True)


class Reseau(nn.Module):
    def __init__(self, a: np.ndarray, cache: int = 64):
        super().__init__()
        self.register_buffer("a", torch.from_numpy(a))
        self.cache = cache
        self.entree = nn.Linear(CARACTERISTIQUES, cache)
        self.voisin = nn.Linear(CARACTERISTIQUES, cache, bias=False)
        self.gru = nn.GRU(cache, cache, batch_first=True)
        self.mix_soi = nn.Linear(cache, cache)
        self.mix_voisins = nn.Linear(cache, cache, bias=False)
        self.tete = nn.Sequential(nn.Linear(cache + CONTEXTE, cache), nn.ReLU(), nn.Linear(cache, HORIZONS))

    def forward(self, x: torch.Tensor, contexte: torch.Tensor) -> torch.Tensor:
        """`x` : (lot, pas, capteurs, caractéristiques) ; `contexte` : (lot, capteurs, CONTEXTE) ; rend (lot, capteurs, horizons)."""
        lot, pas, n, _ = x.shape
        voisins_x = torch.einsum("mn,btnf->btmf", self.a, x)
        z = torch.relu(self.entree(x) + self.voisin(voisins_x))
        z = z.permute(0, 2, 1, 3).reshape(lot * n, pas, self.cache)
        _, h = self.gru(z)
        h = h[0].reshape(lot, n, self.cache)
        h = h + torch.relu(self.mix_soi(h) + self.mix_voisins(torch.einsum("mn,bnh->bmh", self.a, h)))
        return self.tete(torch.cat([h, contexte], dim=-1))


@dataclass
class Donnees:
    """Tout ce qu'il faut pour fabriquer des lots, calculé une fois."""

    vitesse: np.ndarray  # (T, N) centrée réduite, passé rempli
    presente: np.ndarray  # (T, N) 1 si mesurée
    brut_mph: np.ndarray  # (T, N) mph, NaN si absente
    rempli_mph: np.ndarray  # (T, N) mph
    instants_ms: np.ndarray
    profil: voisins.Profil
    moyenne: float
    ecart: float
    habituel: np.ndarray  # (2016, N) centré réduit
    habituel_hors_semaine: np.ndarray  # (semaines, 2016, N)

    def lot(self, t: np.ndarray, apprentissage: bool) -> tuple[torch.Tensor, torch.Tensor]:
        pas = np.arange(-FENETRE + 1, 1)
        idx = t[:, None] + pas[None, :]  # (lot, 12)
        slots = voisins.creneau(self.instants_ms[idx])  # (lot, 12)
        futur = (voisins.creneau(self.instants_ms[t])[:, None] + np.arange(1, HORIZONS + 1)[None, :]) % voisins.PAS_PAR_SEMAINE
        if apprentissage:
            rang = (voisins.semaine(self.instants_ms[t]) - self.profil.premiere_semaine)[:, None]
            hab = self.habituel_hors_semaine[rang, slots]  # (lot, 12, N)
            hab_futur = self.habituel_hors_semaine[rang, futur]
        else:
            hab, hab_futur = self.habituel[slots], self.habituel[futur]
        x = np.stack([self.vitesse[idx], self.presente[idx], hab], axis=-1).astype(np.float32)  # (lot, 12, N, 3)
        actuel = self.vitesse[t][:, None, :]
        ecart_futur = (hab_futur - actuel).transpose(0, 2, 1)  # (lot, N, 6)
        fraction = (self.instants_ms[t] % variables.JOUR_MS) / variables.JOUR_MS
        semaine = (((self.instants_ms[t] // variables.JOUR_MS + 3) % 7) + fraction) / 7.0
        temps = np.stack([np.sin(2 * np.pi * fraction), np.cos(2 * np.pi * fraction), np.sin(2 * np.pi * semaine), np.cos(2 * np.pi * semaine)], axis=1)
        n = self.vitesse.shape[1]
        contexte = np.concatenate([ecart_futur, np.repeat(temps[:, None, :], n, axis=1)], axis=2).astype(np.float32)
        return torch.from_numpy(x), torch.from_numpy(contexte)

    def cibles(self, t: np.ndarray) -> torch.Tensor:
        """Vitesses mesurées à t+1 … t+6 (lot, N, 6), NaN si absentes."""
        return torch.from_numpy(np.stack([self.brut_mph[t + h] for h in range(1, HORIZONS + 1)], axis=2).astype(np.float32))

    def actuelle(self, t: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(self.rempli_mph[t].astype(np.float32))


def preparer(brut: np.ndarray, rempli: np.ndarray, instants_ms: np.ndarray, apprentissage: np.ndarray, k: int = 10) -> Donnees:
    profil = voisins.apprendre(rempli, brut, instants_ms, apprentissage, k=k)
    moyenne, ecart = float(np.nanmean(brut[apprentissage])), float(np.nanstd(brut[apprentissage]))
    norme = lambda v: ((v - moyenne) / ecart).astype(np.float32)  # noqa: E731
    return Donnees(norme(rempli), (~np.isnan(brut)).astype(np.float32), brut, rempli, instants_ms, profil, moyenne, ecart,
                   norme(profil.habituel), norme(profil.habituel_hors_semaine))


def perte(prevu: torch.Tensor, actuel: torch.Tensor, cible: torch.Tensor) -> torch.Tensor:
    """Erreur absolue moyenne en mph sur les cibles mesurées. `prevu` est l'écart appris, `actuel` la vitesse à t (lot, N)."""
    vitesse = actuel[:, :, None] + prevu * ECHELLE_SORTIE
    masque = ~torch.isnan(cible)
    return (vitesse - torch.nan_to_num(cible)).abs()[masque].mean()


def predire(modele: Reseau, donnees: Donnees, t: np.ndarray, apprentissage: bool = False, lot: int = 64) -> np.ndarray:
    """Prévisions en mph, forme (len(t), N, 6)."""
    modele.eval()
    sortie = []
    with torch.no_grad():
        for debut in range(0, len(t), lot):
            tb = t[debut : debut + lot]
            x, contexte = donnees.lot(tb, apprentissage)
            sortie.append((donnees.actuelle(tb)[:, :, None] + modele(x, contexte) * ECHELLE_SORTIE).numpy())
    return np.concatenate(sortie)


def mae_par_horizon(prevu: np.ndarray, brut: np.ndarray, t: np.ndarray) -> list[float]:
    resultats = []
    for h in range(1, HORIZONS + 1):
        reel = brut[t + h]
        masque = ~np.isnan(reel)
        resultats.append(float(np.abs(prevu[:, :, h - 1][masque] - reel[masque]).mean()))
    return resultats
