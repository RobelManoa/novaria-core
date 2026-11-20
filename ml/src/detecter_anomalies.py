"""Point d'entrée : `python3 scripts/dev/dev.py ml-anomalies` (ou ce fichier, avec l'interpréteur de ml/.venv)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anomalies.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
