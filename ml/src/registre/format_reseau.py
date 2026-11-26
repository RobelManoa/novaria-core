"""Écriture du format `novaria-modele-reseau` (IA-16) : côté entraînement, avec PyTorch ; la lecture est dans `lecteur_reseau.py`.

Les poids, l'adjacence et le profil habituel de la semaine sont des nombres ; on les écrit arrondis (poids à 8 décimales, le reste à 6),
ce qui change une prévision de moins de 1e-4 mph (mesuré par le test de parité). Deux exports du même modèle donnent les mêmes octets.
"""

import json

import numpy as np

from registre.lecteur_reseau import NOM, VERSION, FormatInvalide, ModeleReseau, formes_attendues

__all__ = ["FormatInvalide", "ModeleReseau", "exporter"]


def exporter(modele, donnees, meta: dict, capteurs: tuple[str, ...]) -> bytes:
    """Les octets d'un `Reseau` appris et des `Donnees` qui l'ont préparé (moyenne, écart, habituel, voisins)."""
    from prevision.reseau import ECHELLE_SORTIE, adjacence

    etat = {nom: p.detach().cpu().numpy().astype(np.float64) for nom, p in modele.state_dict().items() if nom != "a"}
    if set(etat) != set(formes_attendues(modele.cache)):
        raise FormatInvalide(f"poids inattendus : {sorted(set(etat) ^ set(formes_attendues(modele.cache)))}")
    document = {
        "format": NOM, "version": VERSION, "capteurs": list(capteurs), "moyenne": round(donnees.moyenne, 6), "ecart": round(donnees.ecart, 6),
        "echelle_sortie": ECHELLE_SORTIE, "adjacence": np.round(adjacence(donnees.profil), 6).tolist(),
        "habituel": np.round(donnees.habituel.astype(np.float64), 6).tolist(),
        "poids": {nom: np.round(valeur, 8).tolist() for nom, valeur in sorted(etat.items())}, "meta": meta,
    }
    octets = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    ModeleReseau.depuis_octets(octets)  # ce qu'on écrit doit se relire : sinon on n'écrit rien
    return octets
