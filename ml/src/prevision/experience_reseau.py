"""Expérience d'IA-16 : un réseau spatio-temporel bat-il le HistGradientBoosting à voisins ? (validation SEULEMENT)

    cd ml/src && ../.venv/bin/python -m prevision.experience_reseau [--semaines N] [--epoques E] [--cache H]

`--semaines N` réduit l'apprentissage aux N dernières semaines avant la validation : plus rapide, et on voit si la quantité de
données compte. Le test n'est pas lu.
"""

import argparse
import time

import numpy as np
import torch

from jeu_entrainement import catalogue as cat
from prevision import references, variables
from prevision.experience_voisins import preparer
from prevision.reseau import HORIZONS, Reseau, adjacence, mae_par_horizon, perte, predire
from prevision.reseau import preparer as preparer_reseau

HGB_IA16_VALIDATION = {1: 2.246, 3: 2.779, 6: 3.210}  # prevision-ia16.json, MAE de validation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semaines", type=int, default=0, help="0 : tout l'apprentissage")
    parser.add_argument("--epoques", type=int, default=6)
    parser.add_argument("--cache", type=int, default=64)
    parser.add_argument("--lot", type=int, default=32)
    parser.add_argument("--taux", type=float, default=2e-3)
    arguments = parser.parse_args()
    torch.manual_seed(42)
    np.random.seed(42)
    torch.set_num_threads(10)
    debut = time.time()
    serie, brut, instants, parties, rempli = preparer()
    t_app = parties[cat.TRAIN]
    if arguments.semaines:
        t_app = t_app[-arguments.semaines * 7 * 288 :]
    donnees = preparer_reseau(brut, rempli, instants, parties[cat.TRAIN])
    modele = Reseau(adjacence(donnees.profil), cache=arguments.cache)
    parametres = sum(p.numel() for p in modele.parameters())
    t_app = t_app[t_app + HORIZONS < serie.pas]
    t_val = parties[cat.VALIDATION][parties[cat.VALIDATION] + HORIZONS < serie.pas]
    persistance = [references.calculer(brut, rempli, t_val, h)["persistance"] for h in (1, 3, 6)]
    base = {h: float(np.nanmean(np.abs(p - variables.reponses(brut, t_val, h)))) for h, p in zip((1, 3, 6), persistance)}
    print(f"[{time.time() - debut:4.0f} s] {parametres} poids ; {len(t_app)} pas d'apprentissage ; persistance validation {base}", flush=True)
    optimiseur = torch.optim.AdamW(modele.parameters(), lr=arguments.taux, weight_decay=1e-4)
    pas_total = arguments.epoques * (len(t_app) // arguments.lot)
    planning = torch.optim.lr_scheduler.OneCycleLR(optimiseur, max_lr=arguments.taux, total_steps=pas_total)
    meilleur = None
    for epoque in range(arguments.epoques):
        modele.train()
        ordre = np.random.permutation(t_app)
        somme, nb = 0.0, 0
        for i in range(len(t_app) // arguments.lot):
            tb = np.sort(ordre[i * arguments.lot : (i + 1) * arguments.lot])
            x, contexte = donnees.lot(tb, True)
            prevu = modele(x, contexte)
            erreur = perte(prevu, donnees.actuelle(tb), donnees.cibles(tb))
            optimiseur.zero_grad()
            erreur.backward()
            torch.nn.utils.clip_grad_norm_(modele.parameters(), 5.0)
            optimiseur.step()
            planning.step()
            somme, nb = somme + float(erreur), nb + 1
        prevu_val = predire(modele, donnees, t_val[::2])
        mae = mae_par_horizon(prevu_val, brut, t_val[::2])
        gains = {h: 1 - mae[h - 1] / base[h] for h in (1, 3, 6)}
        print(f"[{time.time() - debut:4.0f} s] époque {epoque + 1}/{arguments.epoques} : perte {somme / nb:.3f} ; validation MAE 5/15/30 min "
              f"{mae[0]:.3f}/{mae[2]:.3f}/{mae[5]:.3f} (gain {gains[1] * 100:.1f}/{gains[3] * 100:.1f}/{gains[6] * 100:.1f} %) ; "
              f"HGB IA-16 {HGB_IA16_VALIDATION[1]}/{HGB_IA16_VALIDATION[3]}/{HGB_IA16_VALIDATION[6]}", flush=True)
        if meilleur is None or mae[5] < meilleur:
            meilleur = mae[5]
    print("fait", flush=True)


if __name__ == "__main__":
    main()
