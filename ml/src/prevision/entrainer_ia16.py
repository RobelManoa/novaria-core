"""IA-16 : entraîne le modèle de prévision retenu (variables habituelles et voisines), lit le test UNE fois, exporte le modèle.

    cd ml/src && ../.venv/bin/python -m prevision.entrainer_ia16

Ordre, sans retour en arrière :

1. les variables et le réglage ont été choisis sur la **validation** (`experience_voisins.py`, `experience_reglages.py`) ;
2. pour chaque horizon, on apprend sur l'apprentissage seulement : le modèle retenu et, pour la comparaison, le modèle d'IA-10 ;
3. le **test** est lu une seule fois : le script refuse de recommencer si `ml/evaluation/prevision-ia16.json` existe ;
4. le modèle retenu est écrit au format `novaria-modele-arbres` (sans pickle) dans `var/models/`, relu, et sa prévision comparée à celle de
   scikit-learn sur 2 000 lignes du test (écart maximal écrit dans le résultat).

**Honnêteté.** La période de test a déjà été lue par IA-10 (pour d'autres modèles) : ce n'est pas un test vierge. Aucun choix de ce
script (variables, voisins, réglage) n'a été fait en regardant le test, mais l'auteur connaissait les chiffres d'IA-10.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

from jeu_entrainement import catalogue as cat
from jeu_entrainement.simulation import RACINE
from prevision import HORIZONS_PAS, MPH_EN_KMH, PAS_MIN, evaluation, modeles, references, variables, voisins
from prevision.experience_voisins import PAS_APPRENTISSAGE, preparer
from registre import format_arbres

DOSSIER = RACINE / "ml" / "evaluation"
RESULTAT = DOSSIER / "prevision-ia16.json"
MODELES = RACINE / "var" / "models"
VOISINS = 10
PARAMS_IA16 = {"max_leaf_nodes": 127, "max_iter": 400, "learning_rate": 0.05, "min_samples_leaf": 100}
PARAMS_IA10 = {"max_leaf_nodes": 63, "max_iter": 400, "learning_rate": 0.05}  # choisi sur la validation par IA-10
LIGNES_DE_CONTROLE = 2000


def _apprendre(x: np.ndarray, y: np.ndarray, params: dict):
    garde = ~np.isnan(y)
    return modeles.hgb(params).fit(x[garde], (y - x[:, 0])[garde])


def lancer(progres=print) -> dict:
    if RESULTAT.exists():
        raise SystemExit(f"Refusé : {RESULTAT} existe, le test a déjà été lu (une seule lecture). Supprimer ce fichier serait tricher.")
    debut = time.time()
    serie, brut, instants, parties, rempli = preparer()
    t_app = parties[cat.TRAIN][::PAS_APPRENTISSAGE]
    profil = voisins.apprendre(rempli, brut, instants, parties[cat.TRAIN], k=VOISINS)
    n_base = len(variables.NOMS)
    noms = variables.NOMS + profil.noms()
    capteurs = brut.shape[1]
    sortie: dict = {"jeu": "METR-LA", "capteurs": capteurs, "voisins": VOISINS, "exemples_apprentissage": int(len(t_app) * capteurs),
                    "lecture_du_test": 2, "horizons": {}}
    MODELES.mkdir(parents=True, exist_ok=True)
    for h in HORIZONS_PAS:
        minutes = h * PAS_MIN
        t_val = parties[cat.VALIDATION][parties[cat.VALIDATION] + h < serie.pas]
        t_test = parties[cat.TEST][parties[cat.TEST] + h < serie.pas]
        ya = variables.reponses(brut, t_app, h)
        xa = voisins.matrice_etendue(profil, brut, rempli, instants, t_app, h, en_apprentissage=True)
        nouveau = _apprendre(xa, ya, PARAMS_IA16)
        ancien = _apprendre(xa[:, :n_base], ya, PARAMS_IA10)
        progres(f"[{time.time() - debut:5.0f} s] {minutes} min : modèles appris")
        xv = voisins.matrice_etendue(profil, brut, rempli, instants, t_val, h)
        yv = variables.reponses(brut, t_val, h)
        xt = voisins.matrice_etendue(profil, brut, rempli, instants, t_test, h)
        yt = variables.reponses(brut, t_test, h)
        jour = np.repeat(instants[t_test] // variables.JOUR_MS, capteurs)
        refs = references.calculer(brut, rempli, t_test, h)
        prevu = {"persistance": refs["persistance"], "moyenne_glissante": refs["moyenne_glissante"],
                 "ia10": xt[:, 0] + ancien.predict(xt[:, :n_base]), "ia16": xt[:, 0] + nouveau.predict(xt)}
        bloc = {"validation": {"persistance": evaluation.metriques(references.calculer(brut, rempli, t_val, h)["persistance"], yv),
                               "ia16": evaluation.metriques(xv[:, 0] + nouveau.predict(xv), yv)},
                "test": {nom: evaluation.metriques(p, yt) for nom, p in prevu.items()}, "ecarts": {}}
        sommes = {nom: evaluation.somme_par_jour(p, yt, jour) for nom, p in prevu.items()}
        nombre = sommes["ia16"][1]
        for autre in ("persistance", "moyenne_glissante", "ia10"):
            bloc["ecarts"][autre] = evaluation.ecart_de_mae(sommes["ia16"][0], sommes[autre][0], nombre)
        # Modèle écrit sans pickle, relu, et prévision comparée à scikit-learn.
        octets = format_arbres.exporter(nouveau, noms, {"jeu": "METR-LA", "horizon_pas": h, "horizon_min": minutes, "voisins": VOISINS,
                                                        "variables_de_base": n_base, "unite": "mph", "cible": "vitesse(t+h) - vitesse(t)"})
        fichier = MODELES / f"prevision-metr-la-h{minutes:02d}.json"
        fichier.write_bytes(octets)
        relu = format_arbres.ModeleArbres.depuis_octets(octets)
        echantillon = xt[:: max(1, len(xt) // LIGNES_DE_CONTROLE)][:LIGNES_DE_CONTROLE]
        ecart = float(np.max(np.abs(np.array([relu.predire(list(map(float, ligne))) for ligne in echantillon]) - nouveau.predict(echantillon))))
        bloc["modele"] = {"fichier": str(fichier.relative_to(RACINE)), "octets": len(octets), "sha256": hashlib.sha256(octets).hexdigest(),
                          "arbres": len(relu.arbres), "ecart_max_avec_scikit_learn": ecart, "lignes_de_controle": int(len(echantillon))}
        sortie["horizons"][str(minutes)] = bloc
        progres(f"[{time.time() - debut:5.0f} s] {minutes} min : persistance {bloc['test']['persistance']['mae']:.3f}, IA-10 {bloc['test']['ia10']['mae']:.3f}, "
                f"IA-16 {bloc['test']['ia16']['mae']:.3f} mph ; modèle {len(octets) / 1e6:.1f} Mo, écart {ecart:.2e}")
    sortie["mph_en_kmh"] = MPH_EN_KMH
    RESULTAT.write_text(json.dumps(sortie, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return sortie


if __name__ == "__main__":
    lancer()
    sys.exit(0)
