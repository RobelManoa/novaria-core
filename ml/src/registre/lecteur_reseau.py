"""Lecteur du format `novaria-modele-reseau` (IA-16) : le même fichier que celui du service.

Le code vit dans `services/traitement/app/forecast/reseau.py` (numpy seul) : le service l'exécute, et
l'entraînement le charge ici par son chemin. Il n'y a qu'un exemplaire, donc rien à recopier ni à
comparer. `registre.lecteur_reseau` est ce module même : ses noms et ses constantes sont les siens.
"""

import importlib.util
import sys
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[3]
    / "services"
    / "traitement"
    / "app"
    / "forecast"
    / "reseau.py"
)


def _charger():
    spec = importlib.util.spec_from_file_location(__name__, SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[__name__] = module
    spec.loader.exec_module(module)
    return module


_charger()
