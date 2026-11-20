"""Rend le fichier SQL du job : remplace les jetons {{NOM}} par leurs valeurs, sans jamais en laisser un seul.

Le mot de passe de MongoDB est dans `MONGO_URI`. Le texte rendu n'est écrit nulle part : il part sur l'entrée standard du client
SQL de Flink (`sql-client.sh -f /dev/stdin`), donc ni sur le disque, ni dans les arguments d'un processus.
"""

from __future__ import annotations

import re
from pathlib import Path

JETON = re.compile(r"\{\{([A-Z_]+)\}\}")
# Une valeur ne ferme jamais une chaîne SQL ('), ne casse pas une ligne et n'ouvre pas un jeton : elle reste une valeur.
INTERDITS = ("'", "\n", "\r", "{{", "}}", ";", "\\")


class ErreurSql(ValueError):
    pass


def jetons_du_fichier(texte: str) -> set[str]:
    return set(JETON.findall(texte))


def rendre(texte: str, valeurs: dict[str, str]) -> str:
    """Le SQL avec toutes ses valeurs. Échoue si un jeton n'a pas de valeur, si une valeur est dangereuse ou sans emploi."""
    attendus = jetons_du_fichier(texte)
    manquants = attendus - valeurs.keys()
    if manquants:
        raise ErreurSql(f"jetons sans valeur : {', '.join(sorted(manquants))}")
    inutiles = valeurs.keys() - attendus
    if inutiles:
        raise ErreurSql(f"valeurs sans jeton dans le fichier : {', '.join(sorted(inutiles))}")
    for nom, valeur in valeurs.items():
        if not valeur or any(interdit in valeur for interdit in INTERDITS):
            raise ErreurSql(f"valeur refusée pour {nom} : vide, ou elle contient un caractère qui sortirait de la chaîne SQL")
    rendu = JETON.sub(lambda trouve: valeurs[trouve.group(1)], texte)
    if JETON.search(rendu):
        raise ErreurSql("un jeton reste après le rendu")
    return rendu


def lire(chemin: Path) -> str:
    return Path(chemin).read_text(encoding="utf-8")
