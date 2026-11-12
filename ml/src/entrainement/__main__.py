"""`python -m entrainement validation|test|rapport` (cadrage ML, sections 6 et 7).

- `validation` : réglage sur la validation, validation croisée groupée par run, choix ; écrit `ml/evaluation/selection.json` ;
- `test` : lit le test **une seule fois** pour le candidat choisi et la règle ; écrit `ml/evaluation/resultat-test.json` ;
- `rapport` : écrit `ml/evaluation/resultats.md`.

Code de sortie : 0 étape faite, 1 contrôle de sécurité refusé (jeu modifié, test déjà lu…) ou scikit-learn absent.
"""

import argparse
import sys

from entrainement import candidats, execution, rapport, tracabilite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m entrainement", description=__doc__.splitlines()[0])
    parser.add_argument("etape", choices=("validation", "test", "rapport"))
    arguments = parser.parse_args(argv)
    try:
        if arguments.etape == "validation":
            execution.etape_validation()
        elif arguments.etape == "test":
            execution.etape_test()
        else:
            rapport.ecrire()
            print(f"Écrit : {tracabilite.RAPPORT}")
    except (tracabilite.ControleDeSecurite, candidats.SklearnAbsent, FileNotFoundError) as erreur:
        print(f"Refusé : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
