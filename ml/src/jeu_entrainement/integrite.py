"""Intégrité du jeu avant tout entraînement (cadrage ML, condition S1) : les fichiers sont ceux du manifeste.

Un jeu modifié sans trace (fichier remplacé, ligne altérée, fichier ajouté) fausserait l'entraînement et ferait
citer à `model_runs` une empreinte qui n'est pas celle des données lues. Le contrôle ne lit que le disque : il
recalcule les SHA-256 et les compare à `manifest.json`, qui est versionné dans Git.

`empreinte_attendue` ferme la dernière porte : le manifeste lui-même pourrait être réécrit avec les fichiers. On lui
passe l'empreinte du jeu citée ailleurs (fiche de provenance, document `model_runs`).
"""

import json
from pathlib import Path

from jeu_entrainement.construire import SORTIE_PAR_DEFAUT, empreinte_du_jeu, sha256


def verifier(dossier: Path = SORTIE_PAR_DEFAUT, empreinte_attendue: str | None = None) -> list[str]:
    """Les écarts entre le dossier et son manifeste ; une liste vide veut dire « jeu intact »."""
    chemin = dossier / "manifest.json"
    if not chemin.is_file():
        return [f"manifest.json absent de {dossier}"]
    try:
        manifeste = json.loads(chemin.read_text(encoding="utf-8"))
        fichiers = manifeste["fichiers"]
        attendue = manifeste["empreinte_du_jeu"]
    except (ValueError, KeyError, TypeError) as erreur:
        return [f"manifest.json illisible : {erreur!r}"]
    ecarts = []
    for nom in sorted(fichiers):
        fichier = dossier / nom
        if not fichier.is_file():
            ecarts.append(f"{nom} : fichier manquant")
        elif fichier.stat().st_size != fichiers[nom]["octets"]:
            ecarts.append(f"{nom} : {fichier.stat().st_size} octets, le manifeste en annonce {fichiers[nom]['octets']}")
        elif sha256(fichier) != fichiers[nom]["sha256"]:
            ecarts.append(f"{nom} : SHA-256 différent de celui du manifeste")
    for fichier in sorted(dossier.glob("*.parquet")):
        if fichier.name not in fichiers:
            ecarts.append(f"{fichier.name} : fichier Parquet absent du manifeste")
    if empreinte_du_jeu(fichiers) != attendue:
        ecarts.append("manifest.json : l'empreinte du jeu ne correspond pas à la liste de ses fichiers")
    if empreinte_attendue is not None and attendue != empreinte_attendue:
        ecarts.append(f"empreinte du jeu {attendue} différente de l'empreinte attendue {empreinte_attendue}")
    return ecarts
