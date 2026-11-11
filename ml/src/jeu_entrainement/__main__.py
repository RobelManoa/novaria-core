"""`python -m jeu_entrainement` : construit le jeu v1 dans `data/datasets/novaria-congestion-v1/`.

Code de sortie : 0 jeu construit, 1 catalogue invalide ou simulateur introuvable.
"""

import argparse
import sys
from pathlib import Path

from jeu_entrainement import catalogue, construire


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jeu_entrainement", description=__doc__.splitlines()[0])
    parser.add_argument("--sortie", type=Path, default=construire.SORTIE_PAR_DEFAUT, help="dossier du jeu")
    arguments = parser.parse_args(argv)
    try:
        print(f"Construction de {catalogue.JEU_ID} dans {arguments.sortie}")
        jeu = construire.construire(arguments.sortie, message=print)
    except (catalogue.CatalogueInvalide, ImportError) as erreur:
        print(f"Échec : {erreur}", file=sys.stderr)
        return 1
    for nom, fichier in jeu.manifeste["fichiers"].items():
        print(f"  {nom:<18} {fichier['lignes']:>7} lignes  {fichier['octets'] / 1e6:6.1f} Mo  sha256 {fichier['sha256']}")
    print(f"Empreinte du jeu : {jeu.manifeste['empreinte_du_jeu']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
