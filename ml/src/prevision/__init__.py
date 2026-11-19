"""Prévision de vitesse à court terme sur METR-LA, testée sur un run simulé (IA-10).

Références (persistance, moyenne glissante, naïf saisonnier) contre deux modèles (Ridge, HistGradientBoosting),
évalués par horizon (5, 15 et 30 minutes) avec MAE et RMSE, dans l'ordre du temps. Le jeu METR-LA n'est **pas versionné** :
`source.py` le télécharge et contrôle son empreinte SHA-256 (fiche : `data/datasets/metr-la/PROVENANCE.md`).

- `source.py`     : adresse, taille et empreinte attendues, téléchargement et contrôle (bibliothèque standard) ;
- `donnees.py`    : lecture du fichier HDF5 (h5py) et conversion d'un run simulé en séries de 5 minutes ;
- `variables.py`  : variables des modèles, calculées avec le passé seulement ;
- `references.py` : les trois références ;
- `modeles.py`    : Ridge et HistGradientBoosting (scikit-learn) et leurs réglages ;
- `evaluation.py` : MAE, RMSE, intervalle de confiance par jour ;
- `rapport.py`    : exécution complète, `ml/evaluation/prevision.json` et `prevision-resultats.md`.

Python 3.12 et plus, numpy (installé avec scikit-learn), h5py seulement pour lire le fichier HDF5 (`ml/requirements.txt`).
"""

SEED = 42  # cadrage ML, section 7
PAS_MIN = 5  # une mesure toutes les 5 minutes
HORIZONS_PAS = (1, 3, 6)  # 5, 15 et 30 minutes
HORIZONS_MIN = tuple(h * PAS_MIN for h in HORIZONS_PAS)
MPH_EN_KMH = 1.609344
PAS_PAR_JOUR = 24 * 60 // PAS_MIN  # 288
