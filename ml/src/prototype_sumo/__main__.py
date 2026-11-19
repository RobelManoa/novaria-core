"""`python -m prototype_sumo image|simuler|rejouer|comparer` (IA-11).

- `image`    : construit l'image Docker de SUMO (`novaria-sumo:1.28.0`, environ 2 minutes la première fois) ;
- `calibrer` : mesure la capacité d'une approche (essai de saturation, 3 graines, environ 20 s) ;
- `simuler`  : écrit le carrefour INT_01, lance SUMO dans Docker (5 h simulées, environ 20 s) et exporte `mesures.jsonl` ;
- `rejouer`  : rejoue le run (`--graine`) dans le moteur de fenêtres du traitement ; avec `--pile`, aussi dans la pile Docker du projet ;
- `comparer` : compare le run SUMO au générateur v0 et écrit `ml/evaluation/sumo.json` et `sumo-resultats.md`.

Dossier du run : `var/sumo/sumo-int01-pointe-s42/` (ignoré par Git). Code de sortie : 0 fait, 1 refusé (Docker, SUMO, écart au rejeu).
"""

import argparse
import json
import sys

from jeu_entrainement.simulation import RACINE
from prototype_sumo import SEED, execution, exporter, reseau

DEBUT_S = 6 * 3600  # 06:00, comme le scénario v0 « heure de pointe »
DUREE_S = 5 * 3600


def dossier_du_run(graine: int):
    return RACINE / "var" / "sumo" / exporter.identifiant_du_run(graine)


DOSSIER = dossier_du_run(SEED)
RESULTATS_JSON = RACINE / "ml" / "evaluation" / "sumo.json"
RESULTATS_MD = RACINE / "ml" / "evaluation" / "sumo-resultats.md"


def calibrer() -> float:
    """Essai de saturation : le débit que le carrefour écoule quand 3 000 véhicules par heure se présentent sur chaque approche."""
    from pathlib import Path

    mesures = []
    with execution.dossier_temporaire("sumo-calibration-") as temporaire:
        for graine in (1, 2, 3):
            dossier = Path(temporaire) / f"s{graine}"
            reseau.ecrire(dossier, debut_s=DEBUT_S + 2 * 3600, duree_s=3600, graine=graine, debit_constant_vph=3000)
            execution.lancer(dossier)
            parts = exporter.intervalles(dossier)
            for approche in reseau.APPROCHES:
                total = sum(v["vehicules"] for (a, fin), v in parts.items() if a == approche and fin > 600)
                mesures.append(total / (3000 / 3600))
    moyenne = sum(mesures) / len(mesures)
    print(f"Capacité mesurée : {moyenne:.0f} véhicules/h par approche (min {min(mesures):.0f}, max {max(mesures):.0f}, {len(mesures)} mesures) ; constante du code : {reseau.CAPACITE_MESUREE_VEH_H:g}")
    return moyenne


def simuler(graine: int = SEED) -> dict:
    dossier = dossier_du_run(graine)
    reseau.ecrire(dossier, debut_s=DEBUT_S, duree_s=DUREE_S, graine=graine, capacite_vph=reseau.CAPACITE_MESUREE_VEH_H)
    sortie = execution.lancer(dossier)
    manifeste = exporter.ecrire(dossier, debut_s=DEBUT_S, graine=graine)
    print(sortie.strip().splitlines()[-1] if sortie.strip() else "SUMO : terminé")
    print(f"{manifeste['messages']} événements, de {manifeste['premier']} à {manifeste['dernier']} : {dossier / 'mesures.jsonl'}")
    return manifeste


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype_sumo", description=__doc__.splitlines()[0])
    parser.add_argument("etape", choices=("image", "calibrer", "simuler", "rejouer", "comparer"))
    parser.add_argument("--graine", type=int, default=SEED, help="graine de SUMO (défaut 42) ; une graine neuve donne un run neuf, que la collecte n'a jamais vu")
    parser.add_argument("--pile", action="store_true", help="rejouer : publier aussi sur la collecte de la pile Docker (dev.py up)")
    arguments = parser.parse_args(argv)
    try:
        if arguments.etape == "image":
            execution.construire_image()
            print(f"Image prête : {execution.IMAGE}")
        elif arguments.etape == "calibrer":
            calibrer()
        elif arguments.etape == "simuler":
            simuler(arguments.graine)
        else:
            from prototype_sumo import rejeu

            dossier = dossier_du_run(arguments.graine)
            if not (dossier / "mesures.jsonl").is_file():
                print("Refusé : pas de run à rejouer, lancer d'abord « simuler »", file=sys.stderr)
                return 1
            evenements = rejeu.charger(dossier)
            if arguments.etape == "rejouer":
                bilan = rejeu.rejouer_moteur(evenements)
                print(json.dumps({k: v for k, v in bilan.items() if k != "fenetres"}, indent=2, ensure_ascii=False))
                if arguments.pile:
                    bilan_pile = rejeu.rejouer_pile(evenements, bilan["fenetres"])
                    print(json.dumps(bilan_pile, indent=2, ensure_ascii=False))
                    return 1 if bilan["ecarts"] or bilan_pile["ecarts_avec_le_moteur"] or bilan_pile["fenetres_dans_l_entrepot"] != bilan_pile["fenetres_attendues_dans_l_entrepot"] else 0
                return 1 if bilan["ecarts"] else 0
            from prototype_sumo import rapport

            rapport.ecrire(dossier, RESULTATS_JSON, RESULTATS_MD)
            print(f"Écrit : {RESULTATS_JSON}\nÉcrit : {RESULTATS_MD}")
    except (execution.DockerAbsent, RuntimeError, OSError) as erreur:
        print(f"Refusé : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
