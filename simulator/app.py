"""Simulateur de capteurs IoT du trafic routier (MS-07). Bibliothèque standard seulement.

    python3 simulator/app.py                 service HTTP du conteneur : sonde de santé, runs et anomalies à la demande
    python3 simulator/app.py run ...         rejoue un scénario avec une graine (fichier, sortie standard, collecte)
    python3 simulator/app.py scenarios       liste les scénarios

Le code vit dans le paquet `novaria_sim/` ; ce fichier reste le point d'entrée du conteneur (`CMD python app.py`).
Format émis, scénarios, anomalies et exemples : simulator/README.md.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from novaria_sim import __version__ as VERSION  # noqa: E402
from novaria_sim.cli import main  # noqa: E402
from novaria_sim.service import HEALTH_PATH, health, make_server  # noqa: E402,F401

if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main())
    make_server(int(os.environ.get("PORT", "8000"))).serve_forever()
