"""Fenêtres de trafic fabriquées pour les tests et la preuve de rejeu de DAT-06 : réseau de démonstration (ROAD_001 à ROAD_024).

Valeurs inventées par une formule déterministe (aucune graine aléatoire : le fichier est identique à chaque exécution,
donc son empreinte aussi). Source `SIMULATED`, jamais présentée comme une mesure (ADR-027). Ce n'est pas le générateur
de scénarios de l'ADR-027 (issue séparée) : seulement de quoi remplir `fact_traffic_window` pour prouver le chargement.

    python data/etl/tests/echantillon_fenetres.py --out data/datasets/fenetres/fenetres-demo.csv [--defects]
"""

import argparse
import csv
import io
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

NOMBRE_DE_TRONCONS = 24  # 0005_reseau_demo.sql
DEBUT = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)
FENETRES_PAR_TRONCON = 36  # 3 heures de fenêtres de 5 minutes
ENTETE = (
    "road_segment_id", "window_start", "window_size_s", "source_type", "vehicle_count", "flow_veh_per_min",
    "average_speed_kmh", "occupancy_rate", "max_queue_length_m", "speed_ratio", "sample_count",
    "expected_sample_count", "congestion_state", "classifier_version",
)


def instant(valeur: datetime) -> str:
    return valeur.strftime("%Y-%m-%dT%H:%M:%SZ")


def ligne(numero_troncon: int, rang: int) -> list[str]:
    """Une fenêtre : charge de pointe qui monte puis redescend, plus forte sur les tronçons de rang bas."""
    limite = 30 if numero_troncon > 16 else 50
    charge = max(0.0, math.sin(math.pi * rang / FENETRES_PAR_TRONCON)) * (1.0 - 0.02 * numero_troncon)
    vehicules = round(charge * 150) if rang % 17 else 0  # une fenêtre vide de temps en temps
    vitesse = None if vehicules == 0 else round(limite * (1.0 - 0.7 * charge), 1)
    rapport = None if vitesse is None else round(vitesse / limite, 3)
    etat = "UNKNOWN" if vitesse is None else "FREE_FLOW" if rapport >= 0.7 else "SLOW" if rapport >= 0.4 else "CONGESTED"
    present = 30 - rang % 3
    return [
        f"ROAD_{numero_troncon:03d}", instant(DEBUT + timedelta(minutes=5 * rang)), "300", "SIMULATED", str(vehicules),
        f"{vehicules / 5:.2f}", "" if vitesse is None else f"{vitesse:.1f}", f"{min(1.0, charge * 0.6):.3f}",
        f"{charge * charge * 80:.1f}", "" if rapport is None else f"{rapport:.3f}", str(present), "30", etat, "seuils-v0",
    ]


def fabriquer_fenetres(avec_defauts: bool = False) -> bytes:
    """CSV UTF-8, fins de ligne LF. Avec défauts : une ligne de chaque famille de refus, pour exercer le chemin des rejets."""
    lignes = [ligne(troncon, rang) for troncon in range(1, NOMBRE_DE_TRONCONS + 1) for rang in range(FENETRES_PAR_TRONCON)]
    if avec_defauts:
        doublon = list(lignes[0])
        doublon[4] = "999"
        inconnu = list(lignes[1])
        inconnu[0] = "ROAD_999"
        desaligne = list(lignes[2])
        desaligne[1] = "2026-10-30T06:11:00Z"
        sans_etat = list(lignes[3])
        sans_etat[12] = ""
        lignes += [doublon, inconnu, desaligne, sans_etat]
    sortie = io.StringIO(newline="")
    ecrivain = csv.writer(sortie, lineterminator="\n")
    ecrivain.writerow(ENTETE)
    ecrivain.writerows(lignes)
    return sortie.getvalue().encode("utf-8")


if __name__ == "__main__":
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--out", type=Path, required=True)
    parseur.add_argument("--defects", action="store_true", help="ajoute 4 lignes refusées (doublon, tronçon inconnu, fenêtre désalignée, état vide)")
    options = parseur.parse_args()
    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_bytes(fabriquer_fenetres(options.defects))
    print(f"{options.out} : {NOMBRE_DE_TRONCONS * FENETRES_PAR_TRONCON + (4 if options.defects else 0)} lignes de données")
