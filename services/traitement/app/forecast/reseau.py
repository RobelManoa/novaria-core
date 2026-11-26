"""Lecteur du format `novaria-modele-reseau` : le réseau spatio-temporel de prévision, lu et exécuté
avec numpy seul (IA-16).

Ce fichier est la **source unique** du lecteur : le service l'exécute, et l'entraînement le charge
par son chemin (`ml/src/registre/lecteur_reseau.py`, sans second exemplaire à tenir à jour). Il
n'importe rien du reste du dépôt, ni PyTorch, ni scikit-learn. Le
format est du JSON (jamais de
`pickle`) ; la lecture valide chaque champ, chaque forme de tableau et chaque nombre, et refuse tout
ce qui n'est pas exactement ce format.

Passage avant (identique à `prevision/reseau.py`, vérifié par un test de parité) : pour chacun des N
capteurs, les 12 derniers pas
(vitesse centrée réduite, mesure présente, vitesse habituelle du créneau) passent par une couche qui
mélange le capteur et la moyenne de
ses voisins, puis un GRU ; un second mélange avec les voisins ; une tête reçoit l'état, l'habituel
des 6 pas à venir et l'heure, et rend l'écart à
la persistance pour 5, 10, 15, 20, 25 et 30 minutes.
"""

import json
import math
from dataclasses import dataclass

import numpy as np

NOM = "novaria-modele-reseau"
VERSION = 1
TAILLE_MAX = 64 * 1024 * 1024
CAPTEURS_MAX = 5_000
CACHE_MAX = 512
FENETRE = 12
HORIZONS = 6
CARACTERISTIQUES = 3
CONTEXTE = HORIZONS + 4
PAS_PAR_JOUR = 288
PAS_PAR_SEMAINE = 7 * PAS_PAR_JOUR
JOUR_MS = 86_400_000
CHAMPS = {
    "format",
    "version",
    "capteurs",
    "moyenne",
    "ecart",
    "echelle_sortie",
    "adjacence",
    "habituel",
    "poids",
    "meta",
}


class FormatInvalide(ValueError):
    """Le fichier n'est pas un modèle `novaria-modele-reseau` conforme : on ne le charge pas."""


def formes_attendues(cache: int) -> dict[str, tuple[int, ...]]:
    h = cache
    return {
        "entree.weight": (h, CARACTERISTIQUES),
        "entree.bias": (h,),
        "voisin.weight": (h, CARACTERISTIQUES),
        "gru.weight_ih_l0": (3 * h, h),
        "gru.weight_hh_l0": (3 * h, h),
        "gru.bias_ih_l0": (3 * h,),
        "gru.bias_hh_l0": (3 * h,),
        "mix_soi.weight": (h, h),
        "mix_soi.bias": (h,),
        "mix_voisins.weight": (h, h),
        "tete.0.weight": (h, h + CONTEXTE),
        "tete.0.bias": (h,),
        "tete.2.weight": (HORIZONS, h),
        "tete.2.bias": (HORIZONS,),
    }


def creneau(instants_ms: np.ndarray) -> np.ndarray:
    """Numéro du pas dans la semaine (lundi 00:00 = 0) ; le 1er janvier 1970 est un jeudi."""
    instants_ms = np.asarray(instants_ms, dtype=np.int64)
    jour = instants_ms // JOUR_MS
    return ((jour + 3) % 7) * PAS_PAR_JOUR + (instants_ms % JOUR_MS) * PAS_PAR_JOUR // JOUR_MS


def _sigmoide(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _tableau(valeur, forme: tuple[int, ...], chemin: str) -> np.ndarray:
    try:
        tableau = np.array(valeur, dtype=np.float64)
    except (TypeError, ValueError) as erreur:
        raise FormatInvalide(f"{chemin} : nombres attendus") from erreur
    if tableau.shape != forme:
        raise FormatInvalide(f"{chemin} : forme {forme} attendue, {tableau.shape} reçue")
    if not np.isfinite(tableau).all():
        raise FormatInvalide(f"{chemin} : nombres finis attendus")
    return tableau


def _constante(nom: str):
    raise FormatInvalide(f"constante JSON refusée : {nom}")


@dataclass(frozen=True)
class ModeleReseau:
    capteurs: tuple[str, ...]
    moyenne: float
    ecart: float
    echelle_sortie: float
    adjacence: np.ndarray
    habituel: np.ndarray  # (2016, N) centré réduit
    poids: dict
    cache: int
    meta: dict

    @classmethod
    def depuis_octets(cls, octets: bytes) -> "ModeleReseau":
        if len(octets) > TAILLE_MAX:
            raise FormatInvalide("fichier trop gros")
        try:
            document = json.loads(octets.decode("utf-8"), parse_constant=_constante)
        except (UnicodeDecodeError, json.JSONDecodeError) as erreur:
            raise FormatInvalide(f"JSON illisible : {erreur}") from erreur
        if not isinstance(document, dict) or set(document) != CHAMPS:
            raise FormatInvalide(f"champs attendus exactement : {sorted(CHAMPS)}")
        if document["format"] != NOM or document["version"] != VERSION:
            raise FormatInvalide(f"format {NOM!r} version {VERSION} attendu")
        capteurs = document["capteurs"]
        if (
            not isinstance(capteurs, list)
            or not 0 < len(capteurs) <= CAPTEURS_MAX
            or not all(isinstance(c, str) and c for c in capteurs)
        ):
            raise FormatInvalide(f"capteurs : de 1 à {CAPTEURS_MAX} noms attendus")
        if len(set(capteurs)) != len(capteurs):
            raise FormatInvalide("capteurs : noms en double")
        n = len(capteurs)
        for champ in ("moyenne", "ecart", "echelle_sortie"):
            valeur = document[champ]
            if (
                isinstance(valeur, bool)
                or not isinstance(valeur, (int, float))
                or not math.isfinite(valeur)
            ):
                raise FormatInvalide(f"{champ} : nombre fini attendu")
        if document["ecart"] <= 0 or document["echelle_sortie"] <= 0:
            raise FormatInvalide("ecart et echelle_sortie doivent être positifs")
        if not isinstance(document["meta"], dict):
            raise FormatInvalide("meta : objet attendu")
        poids_bruts = document["poids"]
        if not isinstance(poids_bruts, dict) or "entree.weight" not in poids_bruts:
            raise FormatInvalide("poids : objet attendu")
        try:
            cache = len(poids_bruts["entree.weight"])
        except TypeError as erreur:
            raise FormatInvalide("poids.entree.weight : liste attendue") from erreur
        if not 0 < cache <= CACHE_MAX:
            raise FormatInvalide(f"taille cachée de 1 à {CACHE_MAX} attendue")
        formes = formes_attendues(cache)
        if set(poids_bruts) != set(formes):
            raise FormatInvalide(f"poids attendus exactement : {sorted(formes)}")
        poids = {
            nom: _tableau(poids_bruts[nom], forme, f"poids.{nom}") for nom, forme in formes.items()
        }
        adjacence = _tableau(document["adjacence"], (n, n), "adjacence")
        if (adjacence < 0).any():
            raise FormatInvalide("adjacence : valeurs positives attendues")
        habituel = _tableau(document["habituel"], (PAS_PAR_SEMAINE, n), "habituel")
        return cls(
            tuple(capteurs),
            float(document["moyenne"]),
            float(document["ecart"]),
            float(document["echelle_sortie"]),
            adjacence,
            habituel,
            poids,
            cache,
            document["meta"],
        )

    def predire(
        self, rempli_mph: np.ndarray, presente: np.ndarray, instants_ms: np.ndarray
    ) -> np.ndarray:
        """Prévisions en mph, forme (N, 6), à 5, 10, … 30 minutes après le dernier pas.

        `rempli_mph` (12, N) : les 12 derniers pas, une absence remplie par la dernière mesure
        connue ; `presente` (12, N) : 1 si la
        mesure du pas existe vraiment ; `instants_ms` (12,) : la fin de chaque pas, en
        millisecondes, à intervalles de 5 minutes.
        """
        rempli_mph, presente = (
            np.asarray(rempli_mph, dtype=np.float64),
            np.asarray(presente, dtype=np.float64),
        )
        n = len(self.capteurs)
        if rempli_mph.shape != (FENETRE, n) or presente.shape != (FENETRE, n):
            raise ValueError(f"fenêtre de forme ({FENETRE}, {n}) attendue")
        instants_ms = np.asarray(instants_ms, dtype=np.int64)
        if instants_ms.shape != (FENETRE,):
            raise ValueError(f"{FENETRE} instants attendus")
        if not np.isfinite(rempli_mph).all():
            raise ValueError("la fenêtre remplie ne doit contenir aucune valeur manquante")
        p = self.poids
        vitesse = (rempli_mph - self.moyenne) / self.ecart
        slots = creneau(instants_ms)
        hab = self.habituel[slots]
        x = np.stack([vitesse, presente, hab], axis=-1)  # (12, N, 3)
        voisins_x = np.einsum("mn,tnf->tmf", self.adjacence, x)
        z = np.maximum(
            x @ p["entree.weight"].T + p["entree.bias"] + voisins_x @ p["voisin.weight"].T, 0.0
        )  # (12, N, H)
        hidden = self.cache
        h = np.zeros((n, hidden))
        w_ih, w_hh, b_ih, b_hh = (
            p["gru.weight_ih_l0"],
            p["gru.weight_hh_l0"],
            p["gru.bias_ih_l0"],
            p["gru.bias_hh_l0"],
        )
        for t in range(FENETRE):
            gi, gh = z[t] @ w_ih.T + b_ih, h @ w_hh.T + b_hh
            r = _sigmoide(gi[:, :hidden] + gh[:, :hidden])
            u = _sigmoide(gi[:, hidden : 2 * hidden] + gh[:, hidden : 2 * hidden])
            candidat = np.tanh(gi[:, 2 * hidden :] + r * gh[:, 2 * hidden :])
            h = (1 - u) * candidat + u * h
        h = h + np.maximum(
            h @ p["mix_soi.weight"].T
            + p["mix_soi.bias"]
            + (self.adjacence @ h) @ p["mix_voisins.weight"].T,
            0.0,
        )
        futur = (slots[-1] + np.arange(1, HORIZONS + 1)) % PAS_PAR_SEMAINE
        ecart_futur = (self.habituel[futur] - vitesse[-1][None, :]).T  # (N, 6)
        instant = int(instants_ms[-1])
        fraction = (instant % JOUR_MS) / JOUR_MS
        semaine = (((instant // JOUR_MS + 3) % 7) + fraction) / 7.0
        temps = np.array(
            [
                np.sin(2 * np.pi * fraction),
                np.cos(2 * np.pi * fraction),
                np.sin(2 * np.pi * semaine),
                np.cos(2 * np.pi * semaine),
            ]
        )
        contexte = np.concatenate([ecart_futur, np.repeat(temps[None, :], n, axis=0)], axis=1)
        entree = np.concatenate([h, contexte], axis=1)
        sortie = (
            np.maximum(entree @ p["tete.0.weight"].T + p["tete.0.bias"], 0.0) @ p["tete.2.weight"].T
            + p["tete.2.bias"]
        )
        return rempli_mph[-1][:, None] + sortie * self.echelle_sortie
