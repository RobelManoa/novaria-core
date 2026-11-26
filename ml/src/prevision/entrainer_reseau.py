"""IA-16 : entraîne le réseau spatio-temporel (étape 1), puis lit le test UNE fois et exporte le modèle (étape 2).

    cd ml/src
    ../.venv/bin/python -m prevision.entrainer_reseau entrainer     # environ 40 minutes sur 6 coeurs, validation seulement
    ../.venv/bin/python -m prevision.entrainer_reseau evaluer       # lit le test une fois, écrit le modèle JSON et les résultats

Étape 1 : on apprend sur l'apprentissage, on suit la MAE de **validation** à chaque époque et on garde la meilleure (les poids sont
écrits en `.npz`, jamais en `pickle`). Étape 2 : le script refuse de recommencer si `ml/evaluation/prevision-reseau.json` existe.
La période de test avait déjà été lue par IA-10 et par l'étape du HistGradientBoosting d'IA-16 : ce n'est pas un test vierge.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime

import numpy as np
import torch

from jeu_entrainement import catalogue as cat
from jeu_entrainement.simulation import RACINE
from prevision import evaluation, references, variables
from prevision.experience_voisins import preparer
from prevision.reseau import HORIZONS, Reseau, adjacence, mae_par_horizon, perte, predire
from prevision.reseau import preparer as preparer_reseau
from registre import format_reseau

DOSSIER = RACINE / "ml" / "evaluation"
RESULTAT = DOSSIER / "prevision-reseau.json"
MODELES = RACINE / "var" / "models"
ETAT = MODELES / "reseau-metr-la-etat.npz"
MODELE_JSON = MODELES / "prevision-metr-la-reseau.json"
JOURNAL = MODELES / "reseau-metr-la-apprentissage.json"
EPOQUES, CACHE, LOT, TAUX, VOISINS = 10, 64, 32, 2e-3, 10
HGB_IA16_TEST = {"5": 2.307, "15": 2.876, "30": 3.337}  # prevision-ia16.json


def _preparer():
    torch.manual_seed(42)
    np.random.seed(42)
    torch.set_num_threads(10)
    serie, brut, instants, parties, rempli = preparer()
    donnees = preparer_reseau(brut, rempli, instants, parties[cat.TRAIN], k=VOISINS)
    return serie, brut, instants, parties, rempli, donnees


def entrainer(progres=print) -> None:
    debut = time.time()
    serie, brut, instants, parties, rempli, donnees = _preparer()
    modele = Reseau(adjacence(donnees.profil), cache=CACHE)
    t_app = parties[cat.TRAIN]
    t_app = t_app[t_app + HORIZONS < serie.pas]
    t_val = parties[cat.VALIDATION][parties[cat.VALIDATION] + HORIZONS < serie.pas][::2]
    base = {h: float(np.nanmean(np.abs(references.calculer(brut, rempli, t_val, h)["persistance"] - variables.reponses(brut, t_val, h)))) for h in (1, 3, 6)}
    optimiseur = torch.optim.AdamW(modele.parameters(), lr=TAUX, weight_decay=1e-4)
    pas_par_epoque = len(t_app) // LOT
    planning = torch.optim.lr_scheduler.OneCycleLR(optimiseur, max_lr=TAUX, total_steps=EPOQUES * pas_par_epoque)
    journal, meilleur = [], None
    for epoque in range(EPOQUES):
        modele.train()
        ordre = np.random.permutation(t_app)
        somme = 0.0
        for i in range(pas_par_epoque):
            tb = np.sort(ordre[i * LOT : (i + 1) * LOT])
            x, contexte = donnees.lot(tb, True)
            erreur = perte(modele(x, contexte), donnees.actuelle(tb), donnees.cibles(tb))
            optimiseur.zero_grad()
            erreur.backward()
            torch.nn.utils.clip_grad_norm_(modele.parameters(), 5.0)
            optimiseur.step()
            planning.step()
            somme += float(erreur.detach())
        mae = mae_par_horizon(predire(modele, donnees, t_val), brut, t_val)
        gains = [1 - mae[h - 1] / base[h] for h in (1, 3, 6)]
        journal.append({"epoque": epoque + 1, "perte": somme / pas_par_epoque, "mae_validation": mae, "gain_5_15_30": gains})
        progres(f"[{time.time() - debut:5.0f} s] époque {epoque + 1}/{EPOQUES} : perte {somme / pas_par_epoque:.3f} ; validation {mae[0]:.3f}/{mae[2]:.3f}/{mae[5]:.3f} "
                f"(gain {gains[0] * 100:.1f}/{gains[1] * 100:.1f}/{gains[2] * 100:.1f} %)")
        score = float(np.mean([mae[0], mae[2], mae[5]]))
        if meilleur is None or score < meilleur:
            meilleur = score
            MODELES.mkdir(parents=True, exist_ok=True)
            np.savez(ETAT, **{nom: p.detach().numpy() for nom, p in modele.state_dict().items()})
            progres("    meilleure époque jusqu'ici : poids écrits")
    JOURNAL.write_text(json.dumps({"persistance_validation": base, "epoques": journal}, indent=1) + "\n", encoding="utf-8")


def evaluer(progres=print) -> dict:
    if RESULTAT.exists():
        raise SystemExit(f"Refusé : {RESULTAT} existe, le test a déjà été lu pour ce modèle (une seule lecture).")
    serie, brut, instants, parties, rempli, donnees = _preparer()
    modele = Reseau(adjacence(donnees.profil), cache=CACHE)
    etat = np.load(ETAT, allow_pickle=False)
    modele.load_state_dict({nom: torch.from_numpy(etat[nom]) for nom in etat.files})
    t_test = parties[cat.TEST][parties[cat.TEST] + HORIZONS < serie.pas]
    capteurs = brut.shape[1]
    prevu = predire(modele, donnees, t_test)
    jour = np.repeat(instants[t_test] // variables.JOUR_MS, capteurs)
    sortie: dict = {"jeu": "METR-LA", "capteurs": capteurs, "poids": sum(p.numel() for p in modele.parameters()), "lecture_du_test": 3, "horizons": {}}
    for h in (1, 3, 6):
        minutes = h * 5
        reel = variables.reponses(brut, t_test, h)
        refs = references.calculer(brut, rempli, t_test, h)
        reseau = prevu[:, :, h - 1].reshape(-1)
        bloc = {"persistance": evaluation.metriques(refs["persistance"], reel), "reseau": evaluation.metriques(reseau, reel)}
        sommes = {n: evaluation.somme_par_jour(p, reel, jour) for n, p in (("persistance", refs["persistance"]), ("reseau", reseau))}
        bloc["ecart_contre_persistance"] = evaluation.ecart_de_mae(sommes["reseau"][0], sommes["persistance"][0], sommes["reseau"][1])
        bloc["gain_contre_persistance"] = 1 - bloc["reseau"]["mae"] / bloc["persistance"]["mae"]
        bloc["hgb_ia16_mae_test"] = HGB_IA16_TEST[str(minutes)]
        sortie["horizons"][str(minutes)] = bloc
        progres(f"{minutes} min : persistance {bloc['persistance']['mae']:.3f}, HGB IA-16 {HGB_IA16_TEST[str(minutes)]}, réseau {bloc['reseau']['mae']:.3f} mph "
                f"(gain {bloc['gain_contre_persistance'] * 100:.1f} %)")
    iso = lambda i: datetime.fromtimestamp(int(instants[i]) / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    fiche = {
        "reseau": "metr-la", "jeu": "METR-LA", "type_de_source": "REAL_HISTORICAL",
        "nom": "reseau-spatio-temporel", "version": "1", "entraine_le": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "voisins": VOISINS, "cache": CACHE, "poids": sortie["poids"], "horizons_min": [5, 10, 15, 20, 25, 30], "unite": "mph",
        "periodes": {nom: {"debut": iso(parties[cat_][0]), "fin": iso(parties[cat_][-1]), "pas": int(len(parties[cat_]))}
                     for nom, cat_ in (("apprentissage", cat.TRAIN), ("validation", cat.VALIDATION), ("test", cat.TEST))},
        "test": {minutes: {"mae_modele": b["reseau"]["mae"], "mae_persistance": b["persistance"]["mae"], "gain": b["gain_contre_persistance"],
                           "intervalle_95": [b["ecart_contre_persistance"]["bas"], b["ecart_contre_persistance"]["haut"]],
                           "mae_hgb_ia16": b["hgb_ia16_mae_test"]} for minutes, b in sortie["horizons"].items()},
        "variables": ["vitesse des 12 derniers pas (1 heure)", "mesure présente ou absente", "vitesse habituelle du créneau de la semaine",
                      "habituel des 6 pas à venir moins la vitesse actuelle", "heure de la journée et jour de la semaine",
                      f"les {VOISINS} capteurs voisins de chaque capteur (appris sur l'apprentissage)"],
        "limites": ["appris sur METR-LA seulement : ne sert que ce réseau", "test de METR-LA déjà lu par IA-10 et IA-16 (HGB) : pas un test vierge",
                    "vitesses seules : ni incident ni météo"],
    }
    octets = format_reseau.exporter(modele, donnees, fiche, serie.capteurs)
    MODELE_JSON.write_bytes(octets)
    relu = format_reseau.ModeleReseau.depuis_octets(octets)
    fenetre = np.arange(0, len(t_test), max(1, len(t_test) // 200))[:200]
    ecart = 0.0
    for i in fenetre:
        t = int(t_test[i])
        sortie_np = relu.predire(rempli[t - 11 : t + 1], (~np.isnan(brut[t - 11 : t + 1])).astype(float), instants[t - 11 : t + 1])
        ecart = max(ecart, float(np.abs(sortie_np - prevu[i]).max()))
    sortie["modele"] = {"fichier": str(MODELE_JSON.relative_to(RACINE)), "octets": len(octets), "sha256": hashlib.sha256(octets).hexdigest(),
                        "ecart_max_numpy_contre_torch_mph": ecart, "fenetres_de_controle": int(len(fenetre))}
    progres(f"modèle écrit : {len(octets) / 1e6:.1f} Mo, écart numpy contre PyTorch {ecart:.2e} mph sur {len(fenetre)} fenêtres")
    RESULTAT.write_text(json.dumps(sortie, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return sortie


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("etape", choices=("entrainer", "evaluer"))
    {"entrainer": entrainer, "evaluer": evaluer}[parser.parse_args().etape]()
    sys.exit(0)
