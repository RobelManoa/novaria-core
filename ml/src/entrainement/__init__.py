"""Entraînement et comparaison des modèles de détection de congestion (IA-03).

Suit à la lettre le cadrage ML (docs/06-ia-mlops/cadrage-ml.md) : deux candidats (régression logistique,
HistGradientBoosting) face à la règle de seuils ; au plus 12 réglages par candidat, choisis sur la **validation** ;
validation croisée groupée par run en diagnostic ; le test est lu **une seule fois**, pour le candidat retenu et pour la
règle. scikit-learn n'est importé que par ce paquet (`ml/requirements.txt`, environnement `ml/.venv`).
"""

SEED = 42  # cadrage ML, section 7
