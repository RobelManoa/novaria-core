"""Rejeu et comparaison d'un run SUMO : écrit `ml/evaluation/sumo.json` et `ml/evaluation/sumo-resultats.md`.

Le run principal (graine 42) est celui du dossier `var/sumo/`. Trois variantes disent ce qui change quand on bouge un choix de
modélisation : la **boucle à la ligne d'arrêt** (10 m au lieu de 100 m) et **deux autres graines** de SUMO (43 et 44).
"""

import json
from pathlib import Path

from prototype_sumo import SEED, comparaison, execution, exporter, rejeu, reseau

GRAINES_VOISINES = (43, 44)
DEBUT_S, DUREE_S = 6 * 3600, 5 * 3600


def _variante(graine: int, position_e1_m: float, fen_v0: dict) -> dict:
    with execution.dossier_temporaire("sumo-variante-") as temporaire:
        dossier = Path(temporaire)
        reseau.ecrire(dossier, debut_s=DEBUT_S, duree_s=DUREE_S, graine=graine, capacite_vph=reseau.CAPACITE_MESUREE_VEH_H, position_e1_m=position_e1_m)
        execution.lancer(dossier)
        exporter.ecrire(dossier, debut_s=DEBUT_S, graine=graine)
        bilan = rejeu.rejouer_moteur(rejeu.charger(dossier))
    resume = comparaison.resume(bilan["fenetres"])
    return {"graine": graine, "position_e1_m": position_e1_m, "ecarts_au_rejeu": bilan["ecarts"], "etats": resume["etats"], "ratio_vitesse_moyen": resume["ratio_vitesse_moyen"],
            "ratio_vitesse_min": resume["ratio_vitesse_min"], "file_max_m": resume["file_max_m"], "file_moyenne_m": resume["file_moyenne_m"],
            "vehicules_par_minute_moyen": resume["vehicules_par_minute_moyen"]}


def executer(dossier: Path, progres=print) -> dict:
    evenements = rejeu.charger(dossier)
    bilan = rejeu.rejouer_moteur(evenements)
    manifeste = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
    fen_v0 = comparaison.run_v0(SEED, "06:00", DUREE_S)
    resultat = {"run": manifeste, "rejeu_moteur": {k: v for k, v in bilan.items() if k != "fenetres"}, "comparaison": comparaison.comparer(bilan["fenetres"], fen_v0),
                "capacite_mesuree_vph": reseau.CAPACITE_MESUREE_VEH_H, "variantes": []}
    for graine, position in ((SEED, -10.0), *((g, reseau.POSITION_E1_M) for g in GRAINES_VOISINES)):
        progres(f"variante : graine {graine}, boucle à {abs(position):g} m de la ligne d'arrêt")
        resultat["variantes"].append(_variante(graine, position, fen_v0))
    return resultat


def _n(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def _pc(x: float) -> str:
    return f"{100 * x:.0f} %"


def markdown(r: dict) -> str:
    c, s, v = r["comparaison"], r["comparaison"]["sumo"], r["comparaison"]["v0"]
    m = r["rejeu_moteur"]
    ligne = ["# Prototype SUMO : résultats du rejeu et de la comparaison (IA-11)", "",
             "Fichier **généré** par `python3 scripts/dev/dev.py ml-sumo comparer` (ne pas modifier à la main) ; l'analyse est dans [`prototype-sumo.md`](../../docs/06-ia-mlops/prototype-sumo.md).", "",
             "## Le run", "", f"- Run `{r['run']['run_id']}` : carrefour {c['intersection']}, 5 h simulées à partir de 06:00, graine {r['run']['seed']}, {r['run']['messages']} événements, empreintes SHA-256 dans le manifeste.",
             f"- Capacité mesurée d'une approche : {_n(r['capacite_mesuree_vph'], 0)} véhicules/h (le v0 suppose 1 400).", "",
             "## Rejeu dans le moteur de fenêtres du traitement", "", "| Contrôle | Résultat |", "|---|---|",
             f"| Messages acceptés | {m['mesures_acceptees']} sur {m['messages']} |", f"| Fenêtres d'une minute | {m['fenetres_1_minute']} (4 approches × 300 minutes) |",
             f"| Véhicules conservés | {m['vehicules']} dans les fenêtres |", f"| Écarts | {'aucun' if not m['ecarts'] else '; '.join(m['ecarts'])} |", "",
             "## SUMO contre le générateur v0 (mêmes minutes, mêmes quatre approches)", "", "| Mesure | SUMO | v0 |", "|---|---|---|",
             f"| Véhicules par minute et approche (moyenne ; écart type) | {_n(s['vehicules_par_minute_moyen'], 1)} ; {_n(s['vehicules_par_minute_ecart_type'], 1)} | {_n(v['vehicules_par_minute_moyen'], 1)} ; {_n(v['vehicules_par_minute_ecart_type'], 1)} |",
             f"| Ratio de vitesse (moyenne ; écart type ; minimum) | {_n(s['ratio_vitesse_moyen'])} ; {_n(s['ratio_vitesse_ecart_type'])} ; {_n(s['ratio_vitesse_min'])} | {_n(v['ratio_vitesse_moyen'])} ; {_n(v['ratio_vitesse_ecart_type'])} ; {_n(v['ratio_vitesse_min'])} |",
             f"| File moyenne ; maximale (m) | {_n(s['file_moyenne_m'], 0)} ; {_n(s['file_max_m'], 0)} | {_n(v['file_moyenne_m'], 0)} ; {_n(v['file_max_m'], 0)} |",
             f"| Minutes annoncées FREE_FLOW / SLOW / CONGESTED par la règle de seuils | {_pc(s['etats']['FREE_FLOW'])} / {_pc(s['etats']['SLOW'])} / {_pc(s['etats']['CONGESTED'])} | {_pc(v['etats']['FREE_FLOW'])} / {_pc(v['etats']['SLOW'])} / {_pc(v['etats']['CONGESTED'])} |", "",
             "Corrélation des profils de demande par tranche de 30 minutes : "
             + ("non définie (un profil est constant)" if c["correlation_profil_de_demande"] is None else _n(c["correlation_profil_de_demande"])) + ".", "",
             "### Par tranche de 30 minutes (moyenne des quatre approches)", "",
             "| Début | Véhicules/min SUMO | v0 | Ratio SUMO | v0 | File SUMO (m) | v0 (m) |", "|---|---|---|---|---|---|---|"]
    for a, b in zip(s["tranches"], v["tranches"], strict=True):
        heures = 6 * 60 + a["tranche"] * 30
        ligne.append(f"| {heures // 60:02d}:{heures % 60:02d} | {_n(a['vehicules_par_minute'], 1)} | {_n(b['vehicules_par_minute'], 1)} | {_n(a['ratio_vitesse'])} | {_n(b['ratio_vitesse'])} | {_n(a['file_m'], 0)} | {_n(b['file_m'], 0)} |")
    ligne += ["", "## Sensibilité", "", "| Variante | Ratio moyen | Ratio minimal | FREE_FLOW / SLOW / CONGESTED | File max (m) | Écarts au rejeu |", "|---|---|---|---|---|---|"]
    for x in r["variantes"]:
        nom = f"graine {x['graine']}, boucle à {abs(x['position_e1_m']):g} m"
        e = x["etats"]
        ligne.append(f"| {nom} | {_n(x['ratio_vitesse_moyen'])} | {_n(x['ratio_vitesse_min'])} | {_pc(e['FREE_FLOW'])} / {_pc(e['SLOW'])} / {_pc(e['CONGESTED'])} | {_n(x['file_max_m'], 0)} | {'aucun' if not x['ecarts_au_rejeu'] else 'oui'} |")
    return "\n".join(ligne) + "\n"


def ecrire(dossier: Path, chemin_json: Path, chemin_md: Path, progres=print) -> dict:
    r = executer(dossier, progres)
    chemin_json.write_text(json.dumps(r, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    chemin_md.write_text(markdown(r), encoding="utf-8", newline="\n")
    return r
