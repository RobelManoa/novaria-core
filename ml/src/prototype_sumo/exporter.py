"""Sorties des détecteurs de SUMO → événements `novaria.iot.measurement.v1` (contrats `contracts/events/`).

| Champ du contrat | Vient de |
|---|---|
| `vehicle_count` | somme des `nVehContrib` des boucles (E1) des voies de l'approche, sur l'intervalle de 10 s |
| `average_speed_kmh` | vitesse moyenne des boucles, pondérée par leur nombre de véhicules (m/s × 3,6) ; absente sans véhicule |
| `occupancy_rate` | moyenne des `occupancy` (en %) des voies, divisée par 100 |
| `queue_length_m` | plus grande `maxJamLengthInMeters` des détecteurs de zone (E2) de l'approche |
| `sensor_id`, `road_segment_id` | l'approche de INT_01 du réseau v0 (N = SENSOR_001 … W = SENSOR_004) |
| `provenance` | `SIMULATED`, scénario `sumo-carrefour-int01-pointe`, graine de SUMO |

Le constructeur d'événements est celui du simulateur v0 (`novaria_sim.events`) : même enveloppe, même identifiant
`<run>:<capteur>:<ms>`, même corrélation. Seule `source` change (`sumo/<run>` au lieu de `simulateur/<run>`).

Aucune anomalie n'est injectée et aucune « vérité terrain de congestion » n'est écrite : SUMO n'en a pas.
"""

import hashlib
import json
import xml.etree.ElementTree as ET  # noqa: S405 - fichiers produits par notre propre SUMO, dans un dossier à nous
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jeu_entrainement.simulation import JOUR, importer_le_simulateur
from prototype_sumo import INTERSECTION, SCENARIO
from prototype_sumo.reseau import APPROCHES

SCENARIO_ID = "sumo-carrefour-int01-pointe"
# Le manifeste écrit une empreinte SHA-256 (64 caractères hexadécimaux) sous le nom de chaque fichier. Sous la clé `run.sumocfg`,
# la règle `sumologic-access-token` de gitleaks la prend pour un jeton Sumo Logic (nom contenant « sumo », puis 64 caractères) :
# faux positif. La clé ne contient donc pas « sumo » ; le fichier garde son nom, celui que SUMO attend.
CLES_DU_MANIFESTE = {"run.sumocfg": "run.cfg"}
MS_EN_KMH = 3.6


def identifiant_du_run(graine: int) -> str:
    return f"sumo-int01-pointe-s{graine}"


def _lire(chemin: Path):
    arbre = ET.parse(chemin)  # noqa: S314 - XML produit par notre propre SUMO, dans un dossier à nous
    return arbre.getroot().iter("interval")


def intervalles(dossier: Path) -> dict[tuple[str, float], dict]:
    """Par (approche, fin d'intervalle en secondes) : comptage, vitesse pondérée, occupation et file, voies réunies."""
    mesures: dict[tuple[str, float], dict] = defaultdict(lambda: {"vehicules": 0, "vitesse_poids": 0.0, "poids": 0, "occupations": [], "file": 0.0})
    for el in _lire(dossier / "e1.xml"):
        approche = el.get("id").split("_")[1]
        m = mesures[(approche, float(el.get("end")))]
        n = int(float(el.get("nVehContrib")))
        m["vehicules"] += n
        vitesse = float(el.get("speed"))
        if vitesse >= 0 and n > 0:
            m["vitesse_poids"] += vitesse * n
            m["poids"] += n
        m["occupations"].append(min(100.0, float(el.get("occupancy"))))
    for el in _lire(dossier / "e2.xml"):
        approche = el.get("id").split("_")[1]
        m = mesures[(approche, float(el.get("end")))]
        m["file"] = max(m["file"], float(el.get("maxJamLengthInMeters")))
    return mesures


def evenements(dossier: Path, *, debut: datetime, graine: int) -> list[dict]:
    """Les événements du run, triés par instant puis par capteur."""
    _, reseau, _, _ = importer_le_simulateur()
    from novaria_sim import events

    run_id = identifiant_du_run(graine)
    segments = {s.approach: s for s in reseau.SEGMENTS if s.intersection_id == INTERSECTION}
    sortie = []
    for (approche, fin), m in sorted(intervalles(dossier).items(), key=lambda x: (x[0][1], APPROCHES.index(x[0][0]))):
        if fin <= 0:
            continue
        vitesse = round(m["vitesse_poids"] / m["poids"] * MS_EN_KMH, 1) if m["poids"] else None
        drapeaux = ["MISSING_SPEED"] if m["vehicules"] and vitesse is None else []
        document = events.build_event(
            run_id=run_id, scenario_id=SCENARIO_ID, seed=graine, segment=segments[approche], instant=debut + timedelta(seconds=fin),
            vehicle_count=m["vehicules"], speed_kmh=vitesse, occupancy_rate=round(sum(m["occupations"]) / len(m["occupations"]) / 100.0, 3),
            queue_length_m=round(min(m["file"], 10000.0), 1), quality_block=events.quality("PARTIAL" if drapeaux else "VALID", drapeaux))
        document["source"] = f"sumo/{run_id}"
        sortie.append(document)
    return sortie


def debut_du_run(debut_s: int) -> datetime:
    return datetime(*JOUR, tzinfo=UTC) + timedelta(seconds=debut_s)


def ecrire(dossier: Path, *, debut_s: int, graine: int) -> dict:
    """Écrit `mesures.jsonl` et `manifest.json` (empreintes SHA-256) dans `dossier`, et rend le manifeste."""
    importer_le_simulateur()
    from novaria_sim import events

    liste = evenements(dossier, debut=debut_du_run(debut_s), graine=graine)
    texte = "".join(events.to_line(e) + "\n" for e in liste)
    (dossier / "mesures.jsonl").write_text(texte, encoding="utf-8", newline="\n")
    manifeste = {
        "run_id": identifiant_du_run(graine), "source": "SUMO (Simulation of Urban MObility) 1.28.0, image novaria-sumo:1.28.0", "scenario_id": SCENARIO_ID,
        "scenario_v0_de_reference": SCENARIO, "seed": graine, "intersection": INTERSECTION, "messages": len(liste), "premier": liste[0]["time"] if liste else None,
        "dernier": liste[-1]["time"] if liste else None,
        "fichiers": {CLES_DU_MANIFESTE.get(nom, nom): hashlib.sha256((dossier / nom).read_bytes()).hexdigest()
                     for nom in ("mesures.jsonl", "net.net.xml", "flows.rou.xml", "detectors.add.xml", "run.sumocfg") if (dossier / nom).is_file()},
        "verite_terrain": "aucune : SUMO ne fournit pas d'état de congestion voulu (voir docs/06-ia-mlops/prototype-sumo.md)",
    }
    (dossier / "manifest.json").write_text(json.dumps(manifeste, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifeste
