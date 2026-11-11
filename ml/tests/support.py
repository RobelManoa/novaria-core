"""Chemins d'import et petits jeux de test partagés (le code est dans `ml/src`, le simulateur dans `simulator/`)."""

import sys
from pathlib import Path

RACINE_ML = Path(__file__).resolve().parents[1]
RACINE = RACINE_ML.parent
sys.path.insert(0, str(RACINE_ML / "src"))

from jeu_entrainement import catalogue as cat  # noqa: E402

HEURE = 3600


def petit_catalogue(decalage_graine: int = 0) -> tuple:
    """Neuf runs courts (trois scénarios, un run par ensemble) : assez pour tout vérifier en quelques secondes."""
    runs = []
    plages = {"journee-calme": ("09:00", 1200), "heure-de-pointe": ("07:15", 1500), "incident-ponctuel": ("08:00", 1500)}
    graine = 100 + decalage_graine
    for scenario, (debut, duree) in plages.items():
        court = {"journee-calme": "calme", "heure-de-pointe": "pointe", "incident-ponctuel": "incident"}[scenario]
        for ensemble in cat.ENSEMBLES:
            anomalies = {
                cat.TRAIN: (),
                cat.VALIDATION: ("muet:sensor=SENSOR_003,at=+300,duration=3m",),
                cat.TEST: ("doublon:sensor=SENSOR_001,at=+120,duration=5m,copies=2,lag=3",),
            }[ensemble]
            runs.append(cat.RunSpec(f"t-{court}-{ensemble}", scenario, graine, ensemble, debut, duree, anomalies))
            graine += 1
    return tuple(runs)
