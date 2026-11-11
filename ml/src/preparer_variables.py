"""Point d'entrée : `python3 ml/src/preparer_variables.py` (sous Windows : `py -3 ml/src/preparer_variables.py`)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preparation.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
