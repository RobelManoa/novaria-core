"""Fenêtres d'une minute d'un run, calculées par le moteur du traitement en flux (MS-09).

Le jeu ne réimplémente pas l'agrégation : il rejoue les messages du run, dans l'ordre de livraison, dans le
`WindowEngine` de `services/traitement/app/flux/windows.py`. Les règles sont donc celles de l'entrepôt
(dictionnaire de données, section 6) : une mesure appartient à la fenêtre qui contient le début de son
intervalle ; une mesure suspecte et un doublon sont écartés ; un message trop en retard est refusé (`LATE`) ;
un capteur muet donne une fenêtre vide. Ce que le modèle apprend est ce que la production lui donnera.
"""

import sys
from collections import Counter
from datetime import UTC, datetime

from jeu_entrainement.simulation import RACINE, ResultatRun

TAILLE_S = 60


def importer_le_moteur():
    dossier = RACINE / "services" / "traitement"
    if not (dossier / "app" / "flux" / "windows.py").is_file():
        raise ImportError(f"moteur de fenêtres introuvable : {dossier / 'app' / 'flux' / 'windows.py'}")
    if str(dossier) not in sys.path:
        sys.path.insert(0, str(dossier))
    from app.flux.model import Measurement
    from app.flux.windows import WindowEngine

    return WindowEngine, Measurement


def epoch_ms(texte: str) -> int:
    return int(datetime.fromisoformat(texte.replace("Z", "+00:00")).astimezone(UTC).timestamp() * 1000)


def mesure(evenement: dict, mesure_type):
    """Un message du simulateur en `Measurement` du moteur (ce que le nettoyage de `iot.raw` rendrait)."""
    donnees = evenement["data"]
    provenance = donnees["provenance"]
    return mesure_type(
        id=evenement["id"],
        run_id=provenance["run_id"],
        source_type=provenance["source_type"],
        scenario_id=provenance.get("scenario_id"),
        seed=provenance.get("seed"),
        dataset_id=provenance.get("dataset_id"),
        sensor_id=donnees["sensor_id"],
        road_segment_id=donnees["road_segment_id"],
        intersection_id=donnees["intersection_id"],
        time_ms=epoch_ms(evenement["time"]),
        interval_s=donnees["interval_s"],
        vehicle_count=donnees["vehicle_count"],
        speed_kmh=donnees.get("average_speed_kmh"),
        occupancy_rate=donnees.get("occupancy_rate"),
        queue_length_m=donnees.get("queue_length_m"),
        status=donnees["quality"]["status"],
        flags=tuple(donnees["quality"].get("flags", ())),
        correlation_id=evenement.get("correlation_id"),
    )


def calculer(resultat: ResultatRun) -> tuple[dict[tuple[str, int], object], Counter]:
    """Les fenêtres d'une minute de chaque tronçon, par (tronçon, début en ms), et les compteurs du moteur."""
    moteur_type, mesure_type = importer_le_moteur()
    moteur = moteur_type()
    fenetres: dict[tuple[str, int], object] = {}

    def retenir(emissions) -> None:
        for emission in emissions:
            if emission.window.size_s == TAILLE_S:
                fenetres[(emission.window.road_segment_id, emission.window.start_ms)] = emission.window

    dernier = 0.0
    for livraison in resultat.livraisons:
        dernier = livraison.emit_at.timestamp()
        retenir(moteur.add(mesure(livraison.event, mesure_type), dernier).emissions)
    retenir(moteur.flush_idle(dernier + 60).emissions)
    return fenetres, moteur.stats
