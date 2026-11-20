"""Les messages du prototype : ceux du simulateur MS-07 (`simulator/app.py run --stdout`), tels quels.

Le prototype n'écrit pas son propre simulateur : il rejoue celui du dépôt. Même scénario, même graine, mêmes anomalies : mêmes
messages à l'octet près (propriété garantie par MS-07). Le recalcul de vérification relance donc le simulateur au lieu de
relire un fichier, et retrouve exactement ce que le flux a reçu.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
SIMULATEUR = RACINE / "simulator" / "app.py"


@dataclass(frozen=True)
class Essai:
    """Un essai du prototype : tout ce qui fixe les messages produits."""

    scenario: str = "incident-ponctuel"
    graine: int = 7
    debut: str = "2026-10-20T08:00:00Z"
    duree: str = "12m"
    run_id: str = "proto-flux-7"
    anomalies: tuple[str, ...] = field(default_factory=tuple)


def commande(essai: Essai, python: str | None = None) -> list[str]:
    """La ligne de commande du simulateur pour cet essai, messages sur la sortie standard."""
    arguments = [
        python or sys.executable, str(SIMULATEUR), "run", "--scenario", essai.scenario, "--seed", str(essai.graine),
        "--start", essai.debut, "--duration", essai.duree, "--run-id", essai.run_id, "--stdout",
    ]
    for anomalie in essai.anomalies:
        arguments += ["--anomaly", anomalie]
    return arguments


def messages(essai: Essai) -> list[dict]:
    """Tous les messages de l'essai, dans l'ordre de livraison (pas trié par instant d'événement : c'est voulu)."""
    sortie = subprocess.run(commande(essai), capture_output=True, check=False, cwd=RACINE)
    if sortie.returncode != 0:
        raise RuntimeError(f"le simulateur a échoué ({sortie.returncode}) : {sortie.stderr.decode('utf-8', 'replace')[-400:]}")
    return [json.loads(ligne) for ligne in sortie.stdout.decode("utf-8").splitlines() if ligne.strip()]


def ligne_kafka(message: dict, separateur: str = "|") -> bytes:
    """« clé|valeur » pour le producteur de la console Kafka. La clé est `subject` (le carrefour), comme celle de la collecte."""
    cle = message["subject"]
    if separateur in cle or "\n" in cle:
        raise ValueError(f"clé inutilisable : {cle!r}")
    valeur = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return f"{cle}{separateur}{valeur}\n".encode()
