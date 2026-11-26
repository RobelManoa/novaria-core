"""Expérience d'IA-16, suite : quel réglage tire le mieux parti des variables voisines et habituelles ? (validation SEULEMENT)

    cd ml/src && ../.venv/bin/python -m prevision.experience_reglages [horizon_en_pas ...]
"""

import sys
import time

import numpy as np

from jeu_entrainement import catalogue as cat
from prevision import HORIZONS_PAS, PAS_MIN, evaluation, modeles, references, variables, voisins
from prevision.experience_voisins import preparer

CONFIGS = (
    ("K=6, 1 pas sur 3, 200 arbres (référence)", 6, 3, {"max_leaf_nodes": 63, "max_iter": 200, "learning_rate": 0.1}),
    ("K=10", 10, 3, {"max_leaf_nodes": 63, "max_iter": 200, "learning_rate": 0.1}),
    ("K=6, tous les pas", 6, 1, {"max_leaf_nodes": 63, "max_iter": 200, "learning_rate": 0.1}),
    ("K=6, 600 arbres, taux 0,05", 6, 3, {"max_leaf_nodes": 63, "max_iter": 600, "learning_rate": 0.05}),
    ("K=6, 127 feuilles, 400 arbres", 6, 3, {"max_leaf_nodes": 127, "max_iter": 400, "learning_rate": 0.05, "min_samples_leaf": 100}),
)


def main(horizons):
    debut = time.time()
    serie, brut, instants, parties, rempli = preparer()
    for h in horizons:
        t_val = parties[cat.VALIDATION][parties[cat.VALIDATION] + h < serie.pas]
        yv = variables.reponses(brut, t_val, h)
        base = evaluation.metriques(references.calculer(brut, rempli, t_val, h)["persistance"], yv)["mae"]
        print(f"[{time.time() - debut:5.0f} s] horizon {h * PAS_MIN} min : persistance {base:.3f}", flush=True)
        for nom, k, pas, params in CONFIGS:
            profil = voisins.apprendre(rempli, brut, instants, parties[cat.TRAIN], k=k)
            t_app = parties[cat.TRAIN][::pas]
            xa = voisins.matrice_etendue(profil, brut, rempli, instants, t_app, h, en_apprentissage=True)
            ya = variables.reponses(brut, t_app, h)
            g = ~np.isnan(ya)
            xa, cible = xa[g], (ya - xa[:, 0])[g]
            xv = voisins.matrice_etendue(profil, brut, rempli, instants, t_val, h)
            m = evaluation.metriques(xv[:, 0] + modeles.hgb(params).fit(xa, cible).predict(xv), yv)
            print(f"[{time.time() - debut:5.0f} s]   {nom:<42} MAE {m['mae']:.3f} RMSE {m['rmse']:.3f} gain {(1 - m['mae'] / base) * 100:5.1f} %", flush=True)
    print("{}")


if __name__ == "__main__":
    main(tuple(int(a) for a in sys.argv[1:]) or HORIZONS_PAS)
