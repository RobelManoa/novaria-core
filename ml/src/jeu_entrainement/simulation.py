"""Exécution d'un run du simulateur en mémoire : messages livrés et vérité terrain, sans fichier intermédiaire.

Le simulateur du dépôt (`simulator/`, MS-07) est importé tel quel : mêmes messages, mêmes états voulus, mêmes
anomalies que `python3 simulator/app.py run`. Deux exécutions de la même `RunSpec` donnent les mêmes données.
"""

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
JOUR = (2026, 10, 20)  # le jour des exemples du contrat (le simulateur le fixe aussi)


def importer_le_simulateur():
    """Ajoute `simulator/` au chemin d'import et rend les modules utiles ; message clair si le dossier manque."""
    dossier = RACINE / "simulator"
    if not (dossier / "novaria_sim").is_dir():
        raise ImportError(f"simulateur introuvable : {dossier / 'novaria_sim'} (lancer depuis le dépôt Novaria Core)")
    if str(dossier) not in sys.path:
        sys.path.insert(0, str(dossier))
    from novaria_sim import anomalies, network, run, scenarios

    return anomalies, network, run, scenarios


@dataclass(frozen=True)
class ResultatRun:
    spec: object
    config: object
    livraisons: list  # Delivery(emit_at, event), dans l'ordre de livraison
    verite: list[dict]  # une ligne par capteur et par intervalle (état voulu, anomalies)
    version_du_generateur: str


def executer(spec) -> ResultatRun:
    anomalies, _, run, _ = importer_le_simulateur()
    heures, minutes = (int(x) for x in spec.debut.split(":"))
    debut = datetime(*JOUR, heures, minutes, tzinfo=UTC)
    liste = tuple(anomalies.parse_spec(texte, debut) for texte in spec.anomalies)
    config = run.default_config(spec.scenario_id, spec.seed, spec.run_id, start=debut, duration_s=spec.duree_s, anomalies=liste)
    execution = run.Run(config)
    livraisons, verite = [], []
    while not execution.done:
        tick = execution.step()
        livraisons += tick.deliveries
        verite += tick.truth
    livraisons += execution.finish()
    return ResultatRun(spec, config, livraisons, verite, generator_version())


def generator_version() -> str:
    importer_le_simulateur()
    from novaria_sim import __version__

    return __version__
