"""Point d'entrée : `python3 scripts/dev/dev.py ml-sumo image|calibrer|simuler|rejouer|comparer` (ou ce fichier)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prototype_sumo.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
