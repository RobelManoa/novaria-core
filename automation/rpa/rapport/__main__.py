"""`python -m rapport` : produit le rapport sans Robot Framework (mêmes étapes que la suite Robot).

    NOVARIA_RPA_USER=... NOVARIA_RPA_PASSWORD=... python -m rapport --api http://127.0.0.1:8000 \
        --dossier var/reports [--debut AAAA-MM-JJ] [--fin AAAA-MM-JJ]

Code de sortie : 0 rapport déposé, 1 échec (une notification d'erreur est écrite), 2 saisie invalide.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from rapport import api, chaine, depot, periode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rapport", description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="adresse de la passerelle")
    parser.add_argument("--dossier", type=Path, default=Path("var/reports"), help="dossier de dépôt")
    parser.add_argument("--debut", help="début de la période, AAAA-MM-JJ (semaine précédente par défaut)")
    parser.add_argument("--fin", help="fin exclue, AAAA-MM-JJ (début + 7 jours par défaut)")
    arguments = parser.parse_args(argv)
    try:
        resultat = chaine.produire(arguments.api, arguments.dossier, debut=arguments.debut, fin=arguments.fin)
    except (periode.PeriodeInvalide, chaine.IdentifiantsAbsents) as erreur:
        print(f"Saisie invalide : {erreur}", file=sys.stderr)
        return 2
    except api.ErreurApi as erreur:
        depot.notifier(arguments.dossier, "ERREUR", f"rapport non produit : {erreur}", datetime.now(UTC))
        print(f"Échec : {erreur}", file=sys.stderr)
        return 1
    print(json.dumps({**resultat.metadonnees, "remplace": resultat.remplace}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
