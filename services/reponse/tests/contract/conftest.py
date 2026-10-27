"""Accès aux contrats du dépôt (`contracts/`) depuis les tests de conformité d'un service."""

import sys
from pathlib import Path


def trouver_contrats() -> Path:
    for dossier in Path(__file__).resolve().parents:
        if (dossier / "contracts" / "topics.json").is_file():
            return dossier / "contracts"
    raise RuntimeError("dossier contracts/ introuvable : lancer les tests dans le dépôt")


CONTRACTS = trouver_contrats()

for chemin in (CONTRACTS, CONTRACTS / "tests"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))
