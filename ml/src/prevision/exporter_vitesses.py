"""Écrit un réseau de vitesses au format de chargement de l'entrepôt : `manifeste.json` et `mesures.csv` (IA-16).

    cd ml/src && ../.venv/bin/python -m prevision.exporter_vitesses [--depuis 2012-05-23]

Pour METR-LA : le dossier `data/datasets/vitesses/metr-la/` (ignoré par Git, comme tout `data/datasets/`) que
`python3 scripts/dev/dev.py etl-vitesses --reseau metr-la` charge ensuite dans `dwh.speed_*`. Seules les vitesses mesurées sont écrites :
une mesure absente (0 dans le fichier d'origine) n'a pas de ligne. L'heure de METR-LA est une heure murale sans fuseau : elle est écrite
comme un instant UTC, comme pour l'entraînement (le modèle ne regarde que l'heure et le jour de la semaine). Les identifiants de capteurs
sont ceux du fichier d'origine.

Licence des données non établie (fiche de provenance) : le dossier écrit reste local, jamais commité ni copié dans une image.
"""

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from prevision import donnees, source
from prevision.donnees import Serie
from jeu_entrainement.simulation import RACINE

DOSSIER = RACINE / "data" / "datasets" / "vitesses" / "metr-la"
DEPUIS = "2012-05-23"  # le début de la validation : la validation et le test, avec leur historique, suffisent à la démonstration


def ecrire(serie: Serie, dossier: Path, depuis: str = DEPUIS) -> dict:
    """Écrit manifeste et mesures de `serie` à partir du jour `depuis` ; rend les nombres écrits."""
    debut_ms = int(datetime.fromisoformat(depuis).replace(tzinfo=UTC).timestamp() * 1000)
    gardes = np.flatnonzero(serie.instants_ms >= debut_ms)
    if len(gardes) == 0:
        raise ValueError(f"aucun pas à partir de {depuis}")
    dossier.mkdir(parents=True, exist_ok=True)
    lignes = 0
    with (dossier / "mesures.csv").open("w", encoding="utf-8", newline="\n") as sortie:
        ecrivain = csv.writer(sortie, lineterminator="\n")
        ecrivain.writerow(["observed_at", "sensor_id", "speed"])
        for t in gardes:
            instant = datetime.fromtimestamp(int(serie.instants_ms[t]) / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            for colonne in np.flatnonzero(~np.isnan(serie.vitesses[t])):
                ecrivain.writerow([instant, serie.capteurs[colonne], f"{serie.vitesses[t, colonne]:.2f}"])
                lignes += 1
    manifeste = {
        "network_id": "metr-la", "label": "METR-LA (Los Angeles, 2012)",
        "description": "Vitesses réelles historiques de 207 capteurs d'autoroute, un pas de 5 minutes. Heure murale lue comme UTC. "
                       "Licence des données non établie : usage local seulement.",
        "source_type": "REAL_HISTORICAL", "step_s": 300, "speed_unit": "mph", "sensors": list(serie.capteurs),
    }
    (dossier / "manifeste.json").write_text(json.dumps(manifeste, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"pas": int(len(gardes)), "capteurs": len(serie.capteurs), "mesures": lignes}


def main() -> None:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--depuis", default=DEPUIS, help="premier jour écrit (AAAA-MM-JJ)")
    parseur.add_argument("--sortie", type=Path, default=DOSSIER)
    arguments = parseur.parse_args()
    nombres = ecrire(donnees.charger_metr_la(source.verifier()), arguments.sortie, arguments.depuis)
    print(f"Écrit dans {arguments.sortie} : {nombres['pas']} pas, {nombres['capteurs']} capteurs, {nombres['mesures']} mesures.")


if __name__ == "__main__":
    main()
