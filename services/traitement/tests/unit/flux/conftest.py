"""Accès au validateur des contrats (`contracts/`) pour les tests du flux, comme tests/contract."""

import sys
from pathlib import Path


def _contracts() -> Path:
    for folder in Path(__file__).resolve().parents:
        if (folder / "contracts" / "topics.json").is_file():
            return folder / "contracts"
    raise RuntimeError("dossier contracts/ introuvable : lancer les tests dans le dépôt")


CONTRACTS = _contracts()
if str(CONTRACTS) not in sys.path:
    sys.path.insert(0, str(CONTRACTS))
