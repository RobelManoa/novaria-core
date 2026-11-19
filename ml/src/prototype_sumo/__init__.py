"""Prototype SUMO (IA-11) : un carrefour à feux simulé au niveau du véhicule, exporté au format des événements v0.

SUMO (Simulation of Urban MObility) tourne **dans une image Docker** (`ml/sumo/Dockerfile`) ; le code d'ici n'utilise que la
bibliothèque standard et le simulateur v0 du dépôt (réseau, demande, constructeur d'événements).

- `reseau.py`     : écrit les fichiers d'entrée de SUMO pour le carrefour INT_01 et la demande du scénario v0 ;
- `execution.py`  : construit l'image et lance `netconvert` puis `sumo` dans le conteneur ;
- `exporter.py`   : transforme les sorties des détecteurs en événements `novaria.iot.measurement.v1` ;
- `rejeu.py`      : rejoue les événements dans le moteur de fenêtres du traitement, et dans la pile Docker du projet ;
- `comparaison.py`: compare le run SUMO au générateur v0 sur le même carrefour et la même demande.

Un run SUMO n'a **pas de vérité terrain de congestion** : SUMO ne dit pas « cet état est voulu », la congestion y naît de la
demande et des feux. Voir `docs/06-ia-mlops/prototype-sumo.md`.
"""

SEED = 42
INTERSECTION = "INT_01"
SCENARIO = "heure-de-pointe"
IMAGE = "novaria-sumo:1.28.0"
