"""Point d'entrée : `python3 ml/src/construire_jeu.py` (sous Windows : `py -3 ml/src/construire_jeu.py`)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jeu_entrainement.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
