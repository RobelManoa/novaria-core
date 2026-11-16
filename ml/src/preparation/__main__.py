"""`python -m preparation` : vérifie le découpage et les variables du jeu v1, sans lire le fichier de test.

Code de sortie : 0 tout est conforme, 1 au moins un écart ou jeu absent.
"""

import argparse
import json
import sys
from pathlib import Path

from jeu_entrainement import catalogue, integrite
from preparation import controles, decoupage, donnees, variables
from stockage import ObjetAbsent


def verifier(dossier: Path) -> dict[str, list[str]]:
    """Tous les contrôles, par nom ; chaque valeur est la liste des écarts."""
    manifeste = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
    lignes = []
    for ensemble in donnees.ENSEMBLES_LISIBLES:
        lignes += donnees.charger(ensemble, dossier)
    rapport = {
        "intégrité des fichiers (S1)": integrite.verifier(dossier),
        "découpage du catalogue (run, scénario)": decoupage.verifier_le_decoupage(),
        "découpage du manifeste": decoupage.verifier_contre_le_manifeste(manifeste),
        "variables de la détection": variables.verifier_usage(variables.DETECTION) + [
            f"colonne non classée : {c}" for c in variables.colonnes_non_classees(variables.DETECTION)],
    }
    for horizon in (5, 15):
        usage = variables.prevision(horizon)
        rapport[f"variables de la prévision à {horizon} min"] = variables.verifier_usage(usage) + [
            f"colonne non classée : {c}" for c in variables.colonnes_non_classees(usage)]
    rapport["une ligne par minute, sans trou"] = controles.controle_ordre_et_unicite(lignes)
    rapport["historique = passé de la série"] = controles.controle_historique(lignes)
    rapport["variables inchangées si l'avenir change"] = controles.controle_aucune_dependance_au_futur(lignes)
    rapport["réponses = valeur h minutes plus tard"] = controles.controle_reponses(lignes)
    rapport["calendrier = fonction de l'instant"] = controles.controle_calendrier(lignes)
    return rapport


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m preparation", description=__doc__.splitlines()[0])
    parser.add_argument("--jeu", type=Path, default=donnees.DOSSIER_JEU, help="dossier du jeu")
    parser.add_argument("--json", action="store_true", help="rapport JSON")
    arguments = parser.parse_args(argv)
    try:
        rapport = verifier(arguments.jeu)
    except (FileNotFoundError, ObjetAbsent) as erreur:
        print(f"Échec : {erreur} (construire le jeu : python3 ml/src/construire_jeu.py)", file=sys.stderr)
        return 1
    empreinte = decoupage.empreinte_du_decoupage()
    if arguments.json:
        print(json.dumps({"empreinte_du_decoupage": empreinte, "controles": rapport}, ensure_ascii=False, indent=2))
    else:
        par_ensemble = catalogue.par_ensemble()
        print(f"Découpage par run et par scénario : {', '.join(f'{e} {len(r)} runs' for e, r in par_ensemble.items())}")
        print(f"Empreinte du découpage : {empreinte}")
        for nom, ecarts in rapport.items():
            print(f"  {'OK ' if not ecarts else 'ÉCART'}  {nom}")
            for ecart in ecarts:
                print(f"         {ecart}")
    return 1 if any(rapport.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
