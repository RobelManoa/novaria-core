"""Expérience d'IA-16 : les variables habituelles et voisines améliorent-elles la prévision ? (validation SEULEMENT)

Le test n'est PAS lu ici. On compare, sur la validation de METR-LA, la MAE d'un même HistGradientBoosting avec des
ensembles de variables différents, et on la compare à la persistance. Lancer :

    cd ml/src && ../.venv/bin/python -m prevision.experience_voisins [horizon_en_pas ...]
"""

import json
import sys
import time

import numpy as np

from jeu_entrainement import catalogue as cat
from prevision import HORIZONS_PAS, PAS_MIN, donnees, evaluation, modeles, references, source, variables, voisins
from prevision.rapport import GARDE_MIN, PARTS
from preparation import decoupage

PAS_APPRENTISSAGE = 3
PARAMS = {"max_leaf_nodes": 63, "max_iter": 200, "learning_rate": 0.1}


def preparer():
    serie = donnees.charger_metr_la(source.verifier())
    brut, instants = serie.vitesses, serie.instants_ms
    partition = decoupage.decouper_dans_l_ordre_du_temps([int(i) for i in instants], PARTS, GARDE_MIN)
    parties = {n: np.array(sorted(partition[n])) for n in (cat.TRAIN, cat.VALIDATION, cat.TEST)}
    parties = {n: idx[idx >= variables.DEBUT_MIN] for n, idx in parties.items()}
    rempli = variables.remplir(brut, float(np.nanmean(brut[parties[cat.TRAIN]])))
    return serie, brut, instants, parties, rempli


def main(horizons: tuple[int, ...]) -> None:
    debut = time.time()
    serie, brut, instants, parties, rempli = preparer()
    apprentissage = parties[cat.TRAIN][::PAS_APPRENTISSAGE]
    profil = voisins.apprendre(rempli, brut, instants, parties[cat.TRAIN])
    n_base = len(variables.NOMS)
    sortie: dict = {}
    for h in horizons:
        t_val = parties[cat.VALIDATION][parties[cat.VALIDATION] + h < serie.pas]
        yv = variables.reponses(brut, t_val, h)
        persistance = references.calculer(brut, rempli, t_val, h)["persistance"]
        base_mae = evaluation.metriques(persistance, yv)["mae"]
        xa = voisins.matrice_etendue(profil, brut, rempli, instants, apprentissage, h, en_apprentissage=True)
        ya = variables.reponses(brut, apprentissage, h)
        garde = ~np.isnan(ya)
        xa, cible = xa[garde], (ya - xa[:, 0])[garde]
        xv = voisins.matrice_etendue(profil, brut, rempli, instants, t_val, h)
        noms = variables.NOMS + profil.noms()
        familles = {
            "base (IA-10)": list(range(n_base)),
            "base + habituel": list(range(n_base + 4)),
            "base + voisins": list(range(n_base)) + list(range(n_base + 4, len(noms) - 3)),
            "tout": list(range(len(noms))),
        }
        sortie[h] = {"persistance_mae_validation": base_mae, "exemples": int(len(cible))}
        print(f"[{time.time() - debut:5.0f} s] horizon {h * PAS_MIN} min : persistance MAE validation {base_mae:.3f} ({len(cible)} exemples)", flush=True)
        for nom, colonnes in familles.items():
            modele = modeles.hgb(PARAMS).fit(xa[:, colonnes], cible)
            m = evaluation.metriques(xv[:, 0] + modele.predict(xv[:, colonnes]), yv)
            gain = 1 - m["mae"] / base_mae
            sortie[h][nom] = {"mae": m["mae"], "rmse": m["rmse"], "gain_contre_persistance": gain}
            print(f"[{time.time() - debut:5.0f} s]   {nom:<18} MAE {m['mae']:.3f}  RMSE {m['rmse']:.3f}  gain {gain * 100:5.1f} %", flush=True)
    print(json.dumps(sortie, indent=1))


if __name__ == "__main__":
    main(tuple(int(a) for a in sys.argv[1:]) or HORIZONS_PAS)
