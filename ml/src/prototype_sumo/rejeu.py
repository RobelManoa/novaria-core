"""Rejeu d'un run SUMO par le pipeline du projet : le moteur de fenêtres du traitement, puis la pile Docker complète.

1. **Moteur de fenêtres** (`services/traitement/app/flux/windows.py`, celui qui produit l'entrepôt) : les événements sont
   rejoués dans l'ordre de livraison, sans réseau. On contrôle que rien n'est refusé, que chaque minute de chaque approche
   donne une fenêtre de 6 mesures et que le nombre de véhicules est conservé.
2. **Pile Docker** : les mêmes événements sont publiés sur la collecte (`POST /api/v1/measurements`), traversent Kafka, le flux
   et le pipeline, et on relit `dwh.fact_traffic_window` : mêmes fenêtres, mêmes totaux que dans l'étape 1.
"""

import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from jeu_entrainement import fenetres
from jeu_entrainement.simulation import RACINE

MESURES_PAR_MINUTE = 6


def charger(dossier: Path) -> list[dict]:
    return [json.loads(ligne) for ligne in (dossier / "mesures.jsonl").read_text(encoding="utf-8").splitlines() if ligne]


def rejouer_moteur(evenements: list[dict]) -> dict:
    """Rejoue les événements dans `WindowEngine` et rend le bilan contrôlé (aucune exception : les écarts sont dans `ecarts`)."""
    livraisons = [SimpleNamespace(emit_at=datetime.fromisoformat(e["time"].replace("Z", "+00:00")), event=e) for e in evenements]
    resultat = SimpleNamespace(livraisons=livraisons)
    fenetres_du_run, stats = fenetres.calculer(resultat)
    attendues = Counter(e["data"]["road_segment_id"] for e in evenements)
    par_route = Counter(route for route, _ in fenetres_du_run)
    ecarts = []
    refus = {k: v for k, v in stats.items() if k not in ("accepted", "empty_windows")}
    if refus:
        ecarts.append(f"mesures refusées ou écartées par le moteur : {refus}")
    incompletes = {k: v.sample_count for k, v in fenetres_du_run.items() if v.sample_count != MESURES_PAR_MINUTE}
    if incompletes:
        ecarts.append(f"{len(incompletes)} fenêtres n'ont pas {MESURES_PAR_MINUTE} mesures (exemple : {next(iter(incompletes.items()))})")
    for route, nombre in attendues.items():
        if par_route.get(route, 0) * MESURES_PAR_MINUTE != nombre:
            ecarts.append(f"{route} : {nombre} mesures mais {par_route.get(route, 0)} fenêtres")
    entree, sortie = sum(e["data"]["vehicle_count"] for e in evenements), sum(f.vehicle_count for f in fenetres_du_run.values())
    if entree != sortie:
        ecarts.append(f"véhicules : {entree} dans les messages, {sortie} dans les fenêtres")
    return {"messages": len(evenements), "mesures_acceptees": stats.get("accepted", 0), "fenetres_1_minute": len(fenetres_du_run), "vehicules": sortie,
            "fenetres_par_route": dict(sorted(par_route.items())), "stats_du_moteur": dict(stats), "ecarts": ecarts, "fenetres": fenetres_du_run}


def rejouer_pile(evenements: list[dict], fenetres_moteur: dict | None = None, delai_attente_s: int = 240, progres=print) -> dict:
    """Publie les événements sur la collecte de la pile locale et relit l'entrepôt. Demande la pile démarrée (`dev.py up`).

    Avec `fenetres_moteur` (rendues par `rejouer_moteur`), chaque fenêtre de l'entrepôt est comparée à celle du moteur :
    même nombre de véhicules, même nombre de mesures, même vitesse moyenne (à 0,1 km/h près).

    Une minute **sans aucun véhicule** n'a pas de vitesse : le flux la retient (`DEGRADED_WITHOUT_RATIO`) et l'entrepôt ne la
    reçoit pas. Ce n'est pas un écart mais un comportement du pipeline, rendu à part (`fenetres_retenues_sans_vitesse`) : avec SUMO,
    une file arrêtée au feu rouge sur la boucle donne exactement ce cas (voir `docs/06-ia-mlops/prototype-sumo.md`).
    """
    sys.path.insert(0, str(RACINE / "scripts" / "dev"))
    import parcours

    env = {}
    for ligne in (RACINE / ".env").read_text(encoding="utf-8").splitlines():
        cle, separateur, valeur = ligne.partition("=")
        if separateur and not ligne.lstrip().startswith("#"):
            env[cle.strip()] = valeur.strip().strip('"').strip("'")
    pile = parcours.Pile(env)
    run_id = evenements[0]["data"]["provenance"]["run_id"]
    debut = time.monotonic()
    statuts: Counter = Counter()
    for i in range(0, len(evenements), 200):
        statuts.update(pile.envoyer(evenements[i:i + 200]))
        progres(f"[{time.monotonic() - debut:5.0f} s] {min(i + 200, len(evenements))}/{len(evenements)} messages publiés")
    attendues = len(evenements) // MESURES_PAR_MINUTE
    if fenetres_moteur is not None:
        attendues = sum(1 for w in fenetres_moteur.values() if w.average_speed_kmh is not None)
    fin = time.monotonic() + delai_attente_s
    lignes = [[0, 0]]
    while time.monotonic() < fin:  # les dernières minutes se ferment à l'inactivité du flux : on attend qu'elles arrivent
        lignes = pile.psql(f"SELECT count(*), coalesce(sum(vehicle_count), 0) FROM dwh.fact_traffic_window WHERE run_id = '{run_id}' AND window_size_s = 60;")
        if lignes and int(lignes[0][0]) >= attendues:
            break
        time.sleep(5)
    bilan = {"run_id": run_id, "statuts_de_la_collecte": dict(statuts), "fenetres_attendues_dans_l_entrepot": attendues, "fenetres_dans_l_entrepot": int(lignes[0][0]),
             "vehicules_dans_l_entrepot": int(lignes[0][1]), "duree_s": round(time.monotonic() - debut)}
    if fenetres_moteur is not None:
        lues = pile.psql("SELECT s.road_segment_id, to_char(f.window_start AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'), f.vehicle_count, f.sample_count, f.average_speed_kmh "
                         "FROM dwh.fact_traffic_window f JOIN dwh.dim_road_segment s ON s.road_segment_key = f.road_segment_key "
                         f"WHERE f.run_id = '{run_id}' AND f.window_size_s = 60;")
        bilan["ecarts_avec_le_moteur"], bilan["fenetres_retenues_sans_vitesse"] = _ecarts_entrepot(lues, fenetres_moteur)
    return bilan


def _ecarts_entrepot(lignes: list[list[str]], fenetres_moteur: dict) -> tuple[list[str], list[str]]:
    """(écarts, retenues) : les fenêtres de l'entrepôt qui diffèrent de celles du moteur ou qui manquent d'un côté ; et les minutes sans
    véhicule que le flux n'a pas chargées (absentes de l'entrepôt, sans vitesse dans le moteur)."""
    ecarts, retenues = [], []
    lues = {}
    for route, debut, vehicules, mesures, vitesse in lignes:
        instant = int(datetime.fromisoformat(debut).replace(tzinfo=UTC).timestamp() * 1000)
        lues[(route, instant)] = (int(vehicules), int(mesures), None if vitesse in ("", "None") else float(vitesse))
    for cle in sorted(set(lues) | set(fenetres_moteur)):
        attendue, lue = fenetres_moteur.get(cle), lues.get(cle)
        if attendue is not None and lue is None and attendue.average_speed_kmh is None:
            retenues.append(f"{cle[0]} {datetime.fromtimestamp(cle[1] / 1000, UTC):%H:%M} : {attendue.vehicle_count} véhicule, occupation {attendue.occupancy_rate}")
            continue
        if attendue is None or lue is None:
            ecarts.append(f"{cle[0]} {cle[1]} : fenêtre absente {'du moteur' if attendue is None else 'de l\'entrepôt'}")
            continue
        vitesse = attendue.average_speed_kmh
        if (attendue.vehicle_count, attendue.sample_count) != lue[:2] or (vitesse is None) != (lue[2] is None) or (vitesse is not None and abs(vitesse - lue[2]) > 0.051):
            ecarts.append(f"{cle[0]} {cle[1]} : moteur {attendue.vehicle_count}/{attendue.sample_count}/{vitesse}, entrepôt {lue}")
    return ecarts[:20], retenues
