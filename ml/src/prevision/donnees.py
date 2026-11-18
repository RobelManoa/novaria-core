"""Séries de vitesses : lecture de METR-LA (HDF5) et conversion d'un run simulé en pas de 5 minutes.

Une `Serie` = une matrice (instants × capteurs) de vitesses en **miles par heure** (l'unité de METR-LA), `NaN` quand la
mesure manque. Dans METR-LA, une vitesse de 0 signale une mesure manquante (8,1 % du fichier) : elle devient `NaN`.
"""

from dataclasses import dataclass

import numpy as np

from prevision import MPH_EN_KMH, PAS_MIN

MS_PAR_PAS = PAS_MIN * 60_000


@dataclass(frozen=True)
class Serie:
    nom: str
    instants_ms: np.ndarray  # int64, heure murale « naïve » (METR-LA ne donne pas de fuseau)
    capteurs: tuple[str, ...]
    vitesses: np.ndarray  # float64, forme (instants, capteurs), NaN = manquant

    @property
    def pas(self) -> int:
        return len(self.instants_ms)


def charger_metr_la(chemin) -> Serie:
    """Lit `metr-la.h5` (table pandas « fixed » : `df/axis1` = instants en ns, `df/block0_values` = vitesses). Pas de pandas."""
    import h5py

    with h5py.File(chemin, "r") as f:
        instants_ns = f["df/axis1"][:]
        capteurs = tuple(c.decode("ascii") for c in f["df/axis0"][:])
        valeurs = f["df/block0_values"][:].astype(np.float64)
    if valeurs.shape != (len(instants_ns), len(capteurs)):
        raise ValueError(f"forme inattendue : {valeurs.shape} pour {len(instants_ns)} instants et {len(capteurs)} capteurs")
    ecarts = np.unique(np.diff(instants_ns))
    if len(ecarts) != 1 or ecarts[0] != MS_PAR_PAS * 1_000_000:
        raise ValueError(f"les instants ne sont pas réguliers de {PAS_MIN} minutes : {ecarts[:5]}")
    valeurs[valeurs == 0.0] = np.nan
    return Serie("METR-LA", instants_ns // 1_000_000, capteurs, valeurs)


def serie_depuis_un_run(banc, nom: str | None = None) -> Serie:
    """Un run du simulateur (`anomalies.campagne.Banc`) en pas de 5 minutes : vitesse moyenne pondérée par les véhicules.

    La vitesse des messages est en km/h : elle est convertie en mph pour parler la langue de METR-LA. Un pas sans
    aucun véhicule est manquant (`NaN`). Un message appartient au pas qui contient le **début** de son intervalle.
    """
    debut = int(banc.debut)
    pas = int((banc.fin - banc.debut) // (PAS_MIN * 60))
    capteurs = tuple(sorted({m.capteur for m in banc.mesures}))
    rang = {c: i for i, c in enumerate(capteurs)}
    somme = np.zeros((pas, len(capteurs)))
    poids = np.zeros((pas, len(capteurs)))
    vus: set[str] = set()
    for m in banc.mesures:
        if m.ident in vus or m.vitesse is None or m.vehicules < 1:
            continue
        vus.add(m.ident)
        k = int((m.instant - 10 - banc.debut) // (PAS_MIN * 60))
        if 0 <= k < pas:
            somme[k, rang[m.capteur]] += m.vitesse * m.vehicules
            poids[k, rang[m.capteur]] += m.vehicules
    with np.errstate(invalid="ignore", divide="ignore"):
        vitesses = np.where(poids > 0, somme / poids / MPH_EN_KMH, np.nan)
    instants = (debut + PAS_MIN * 60 * (np.arange(pas) + 1)) * 1000  # fin de chaque pas, comme METR-LA
    return Serie(nom or banc.spec.run_id, instants.astype(np.int64), capteurs, vitesses)
