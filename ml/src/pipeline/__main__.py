"""`python -m pipeline evaluer|porte|enregistrer|tout` : le pipeline MLSecOps (IA-05).

Code de sortie : 0 étape faite (et, pour `porte` et `tout`, modèle accepté), 1 porte fermée (modèle non enregistré),
3 contrôle de sécurité ou décision incohérente (jeu modifié, configuration changée, fichier modifié entre les étapes),
2 configuration ou dépendance absente.

Le registre est MongoDB si `MONGO_URL` est définie (compte `svc_ml`), sinon un dossier de fichiers JSON sous `var/pipeline/` ;
les modèles vont dans `var/models/`.
"""

import argparse
import os
import sys

import pipeline
from entrainement import candidats, tracabilite
from pipeline import decision, etapes
from registre.registre import RegistreErreur
from registre.runs import FichierRunStore, MongoRunStore
from stockage import StockageNonConfigure, ouvrir_magasin


def magasins():
    runs = MongoRunStore.depuis_l_adresse(os.environ["MONGO_URL"]) if os.environ.get("MONGO_URL") else FichierRunStore(pipeline.RUNS)
    return runs, ouvrir_magasin(pipeline.MAGASIN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__.splitlines()[0])
    parser.add_argument("etape", choices=("evaluer", "porte", "enregistrer", "tout"))
    parser.add_argument("--sans-audit", action="store_true", help="n'appelle pas pip-audit (S4 reste « non vérifié »)")
    arguments = parser.parse_args(argv)
    try:
        runs, objets = magasins()
        try:
            if arguments.etape in ("evaluer", "tout"):
                etapes.evaluer(runs=runs, objets=objets, audit=not arguments.sans_audit)
            if arguments.etape in ("porte", "tout"):
                if not etapes.porte(runs=runs, objets=objets):
                    return 1
            if arguments.etape in ("enregistrer", "tout"):
                etapes.enregistrer(runs=runs, objets=objets)
        finally:
            fermer = getattr(runs, "fermer", None)
            if fermer:
                fermer()
    except decision.Bloque as erreur:
        print(f"Porte fermée : {erreur}", file=sys.stderr)
        return 1
    except (tracabilite.ControleDeSecurite, decision.DecisionIncoherente, RegistreErreur) as erreur:
        print(f"Refusé : {erreur}", file=sys.stderr)
        return 3
    except (candidats.SklearnAbsent, FileNotFoundError, KeyError, StockageNonConfigure) as erreur:
        print(f"Configuration : {erreur}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
