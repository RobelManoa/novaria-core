"""Stockage d'objets (ADR-025, LOC-05) : le port `ObjectStore` et son adaptateur local.

Les modèles (`registre`) et les jeux de données (`jeu_entrainement`, `preparation`, `mesures`) rangent et relisent leurs
fichiers par ce port, jamais par un chemin ni par un SDK de cloud. `STORAGE_BACKEND=local` est le seul adaptateur
écrit : S3 est documenté, non exécuté.
"""

from stockage.objets import (
    BACKEND_LOCAL,
    LISTE_MAX,
    TAILLE_MAX,
    TAILLE_MAX_JEU,
    ObjectStore,
    ObjetAbsent,
    ObjetDejaEcrit,
    StockageErreur,
    StockageLocal,
    StockageNonConfigure,
    ouvrir_magasin,
    ouvrir_magasin_de_jeu,
    ranger_a_l_identique,
    sha256,
    verifier_la_cle,
)

__all__ = [
    "BACKEND_LOCAL",
    "LISTE_MAX",
    "TAILLE_MAX",
    "TAILLE_MAX_JEU",
    "ObjectStore",
    "ObjetAbsent",
    "ObjetDejaEcrit",
    "StockageErreur",
    "StockageLocal",
    "StockageNonConfigure",
    "ouvrir_magasin",
    "ouvrir_magasin_de_jeu",
    "ranger_a_l_identique",
    "sha256",
    "verifier_la_cle",
]
