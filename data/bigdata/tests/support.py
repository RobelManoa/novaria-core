"""Chemins d'import des tests : le prototype (`data/bigdata`) et l'ETL de production qu'il réutilise (`data/etl`)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "data" / "bigdata"))
sys.path.insert(0, str(RACINE / "data" / "etl"))

try:
    import pyspark  # noqa: F401

    PYSPARK = True
except ImportError:
    PYSPARK = False
