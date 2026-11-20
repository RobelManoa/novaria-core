"""`python -m prevision telecharger|verifier|evaluer` (IA-10).

- `telecharger` : télécharge `metr-la.h5` (57 Mo) dans `data/datasets/metr-la/` et contrôle taille et SHA-256 ;
- `verifier`    : contrôle le fichier déjà là, sans réseau ;
- `evaluer`     : campagne complète (environ 10 minutes) ; écrit `ml/evaluation/prevision.json` et `prevision-resultats.md`.

Code de sortie : 0 fait, 1 fichier refusé ou absent, scikit-learn ou h5py absent.
"""

import argparse
import sys

from prevision import source  # bibliothèque standard seulement : `telecharger` et `verifier` marchent sans ml/.venv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prevision", description=__doc__.splitlines()[0])
    parser.add_argument("etape", choices=("telecharger", "verifier", "evaluer"))
    arguments = parser.parse_args(argv)
    try:
        if arguments.etape == "telecharger":
            print(f"Fichier conforme : {source.telecharger()}")
        elif arguments.etape == "verifier":
            print(f"Fichier conforme : {source.verifier()} ({source.TAILLE_OCTETS} octets, SHA-256 {source.SHA256})")
        else:
            from prevision import rapport  # numpy, scikit-learn, h5py : environnement ml/.venv

            rapport.ecrire()
            print(f"Écrit : {rapport.JSON}\nÉcrit : {rapport.MARKDOWN}")
    except (source.FichierRefuse, ImportError, OSError) as erreur:
        print(f"Refusé : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
