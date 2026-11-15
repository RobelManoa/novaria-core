"""Point d'entrée : `python3 ml/src/mesurer_reference.py` (sous Windows : `py -3 ml/src/mesurer_reference.py`)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mesures.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
