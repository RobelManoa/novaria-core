"""Exécute la campagne complète et écrit `ml/evaluation/anomalies.json` et `ml/evaluation/anomalies-resultats.md`.

Ordre, sans retour en arrière : 1) apprentissage d'Isolation Forest sur le flux non étiqueté ; 2) seuil du modèle sur la
validation sans anomalie, au budget de fausses alertes commun ; 3) lecture de l'évaluation, une seule fois, pour les règles
et pour le modèle. Les seuils des règles sont dans `regles.py`, fixés sur la validation avant cette exécution.
"""

import json
import statistics
from pathlib import Path

from anomalies import campagne, evaluation, isolation, regles
from jeu_entrainement.simulation import RACINE

SEPARATEUR_DEUX_COLONNES = "|---|---|"

DOSSIER = RACINE / "ml" / "evaluation"
JSON = DOSSIER / "anomalies.json"
MARKDOWN = DOSSIER / "anomalies-resultats.md"
QUANTILES = (1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2)
TYPES = ("muet", "retard", "doublon", "aberrante", "plateau", "chute")
NOMS_TYPES = {"muet": "capteur muet", "retard": "message en retard", "doublon": "doublon", "aberrante": "valeur aberrante", "plateau": "capteur figé (plateau)", "chute": "chute de débit"}


def choisir_seuil(modele, bancs_normaux: list) -> tuple[float, float]:
    """Le seuil le plus permissif qui tient le budget de fausses alertes sur les runs normaux ; et le taux obtenu."""
    notes = [isolation.scores(modele, banc) for banc in bancs_normaux]
    toutes = sorted(note for lot, _ in notes for note in lot)
    heures = sum(banc.duree_h for banc in bancs_normaux)
    retenu, taux = toutes[0], 0.0
    for q in QUANTILES:
        seuil = toutes[max(int(q * len(toutes)), 1) - 1]
        fausses = 0
        for banc, (lot, mesures) in zip(bancs_normaux, notes, strict=True):
            alertes = [regles.Alerte("isolation_forest", m.capteur, m.livre) for note, m in zip(lot, mesures, strict=True) if note <= seuil]
            fausses += len(evaluation.episodes(alertes))
        if fausses / heures <= evaluation.BUDGET_FAUSSES_PAR_HEURE:
            retenu, taux = seuil, fausses / heures
    return retenu, taux


def executer() -> dict:
    bancs = campagne.tous_les_bancs()
    modele, lignes = isolation.entrainer(bancs[campagne.APPRENTISSAGE])
    normaux = [b for b in bancs[campagne.VALIDATION] if not b.injections]
    seuil, taux_validation_if = choisir_seuil(modele, normaux)
    validation_regles = [evaluation.evaluer_banc(b, regles.alertes_des_regles(b)) for b in normaux]

    resultats = {"regles": [], "isolation_forest": []}
    notes_par_banc = []
    for banc in bancs[campagne.EVALUATION]:
        notes = isolation.scores(modele, banc)
        notes_par_banc.append((banc, notes))
        resultats["regles"].append(evaluation.evaluer_banc(banc, regles.alertes_des_regles(banc)))
        resultats["isolation_forest"].append(evaluation.evaluer_banc(banc, isolation.alertes_du_modele(modele, banc, seuil, notes)))

    evalues = bancs[campagne.EVALUATION]
    sources = evaluation.source_par_type(evalues)
    sortie = {
        "protocole": {
            "apprentissage": [b.spec.run_id for b in bancs[campagne.APPRENTISSAGE]], "validation": [b.spec.run_id for b in bancs[campagne.VALIDATION]],
            "evaluation": [b.spec.run_id for b in evalues], "heures_evaluation": round(sum(b.duree_h for b in evalues), 2),
            "injections": sum(len(b.injections) for b in evalues), "budget_fausses_par_heure": evaluation.BUDGET_FAUSSES_PAR_HEURE,
            "lignes_apprentissage": lignes, "seuil_isolation_forest": round(seuil, 4), "arbres": isolation.ARBRES, "echantillon": isolation.ECHANTILLON,
            "parametres_regles": regles.PARAMETRES.__dict__,
        },
        "validation_sans_anomalie": {"regles_fausses_par_heure": round(evaluation.fausses_par_heure(validation_regles), 3),
                                      "isolation_forest_fausses_par_heure": round(taux_validation_if, 3), "heures": round(sum(b.duree_h for b in normaux), 2)},
        "sources": sources, "auc_isolation_forest": {t: None if v is None else round(v, 3) for t, v in isolation.auc_par_type(notes_par_banc).items()}, "detecteurs": {},
    }
    for nom, liste in resultats.items():
        sortie["detecteurs"][nom] = {
            "par_type": evaluation.resume_par_type(liste), "precision": evaluation.precision(liste),
            "fausses_par_heure": round(evaluation.fausses_par_heure(liste), 3),
            "episodes_vrais": sum(r.episodes_vrais for r in liste), "episodes_faux": sum(r.episodes_faux for r in liste),
            "premiere_alerte": evaluation.premiers_detecteurs(liste),
        }
    return sortie


def _n(x: float, decimales: int = 2) -> str:
    return f"{x:.{decimales}f}".replace(".", ",")


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}".replace("%", " %")


def _delai(par: dict) -> str:
    return "—" if par["delai_median_s"] is None else f"{par['delai_median_s']:g} / {par['delai_max_s']:g}"


def markdown(r: dict) -> str:
    p, d = r["protocole"], r["detecteurs"]
    lignes = ["# Détection d'anomalies : résultats (IA-09)", "",
              "Fichier **généré** par `python3 scripts/dev/dev.py ml-anomalies` (ne pas modifier à la main) ; le choix argumenté est dans [`anomalies-comparaison.md`](anomalies-comparaison.md).", "",
              "## Protocole", "",
              f"- Évaluation : {len(p['evaluation'])} runs, {_n(p['heures_evaluation'], 0)} h de réseau simulé, {p['injections']} anomalies injectées (graines 301 et plus, distinctes de la validation et de l'apprentissage).",
              f"- Isolation Forest : {p['arbres']} arbres, {p['echantillon']} mesures par arbre, graine 42, ajusté sur {p['lignes_apprentissage']} messages **non étiquetés** ; seuil de score {_n(p['seuil_isolation_forest'], 3)} réglé sur la validation sans anomalie.",
              f"- Budget commun : au plus {_n(p['budget_fausses_par_heure'], 0)} fausse alerte par heure de réseau sur la validation sans anomalie ({_n(r['validation_sans_anomalie']['heures'], 0)} h). Obtenu : règles {_n(r['validation_sans_anomalie']['regles_fausses_par_heure'])} par heure, Isolation Forest {_n(r['validation_sans_anomalie']['isolation_forest_fausses_par_heure'])} par heure.",
              "- Délai : secondes entre le premier message touché et la première alerte du bon capteur. Colonnes « médian / max ».",
              "- Définitions du rappel, de la précision (par épisode d'alerte) et du délai : en tête de `ml/src/anomalies/evaluation.py`.", "",
              "## Rappel et délai par type d'anomalie", "",
              "| Anomalie | Source | Injectées | Règles : rappel | Règles : délai (s) | Isolation Forest : rappel | Isolation Forest : délai (s) |", "|---|---|---|---|---|---|---|"]
    for type_ in TYPES:
        a, b = d["regles"]["par_type"].get(type_), d["isolation_forest"]["par_type"].get(type_)
        if a is None:
            continue
        lignes.append(f"| {NOMS_TYPES[type_]} | {r['sources'][type_]} | {a['injectees']} | {_pct(a['rappel'])} ({a['detectees']}/{a['injectees']}) | {_delai(a)} | {_pct(b['rappel'])} ({b['detectees']}/{b['injectees']}) | {_delai(b)} |")
    lignes += ["", "## Précision et fausses alertes", "", "| Détecteur | Précision (épisodes) | Épisodes vrais | Épisodes faux | Fausses alertes par heure |", "|---|---|---|---|---|"]
    for nom, titre in (("regles", "Règles"), ("isolation_forest", "Isolation Forest")):
        x = d[nom]
        lignes.append(f"| {titre} | {_pct(x['precision'])} | {x['episodes_vrais']} | {x['episodes_faux']} | {_n(x['fausses_par_heure'])} |")
    lignes += ["", "## Isolation Forest sans seuil : aire sous la courbe ROC des scores", "",
               "Mesure indépendante du seuil : 1 = les messages touchés ont toujours un score plus bas que les messages normaux, 0,5 = au hasard. « — » : aucun message n'existe pendant l'anomalie (capteur muet).", "",
               "| Anomalie | AUC |", SEPARATEUR_DEUX_COLONNES]
    for type_ in TYPES:
        if type_ in r["auc_isolation_forest"]:
            valeur = r["auc_isolation_forest"][type_]
            lignes.append(f"| {NOMS_TYPES[type_]} | {'—' if valeur is None else f'{valeur:.3f}'.replace('.', ',')} |")
    if "muet" not in r["auc_isolation_forest"]:
        lignes.append(f"| {NOMS_TYPES['muet']} | — |")
    lignes += ["", "## Quelle règle donne la première alerte", "", "| Anomalie | Première alerte des règles (nombre d'anomalies) |", SEPARATEUR_DEUX_COLONNES]
    for type_ in TYPES:
        premiere = d["regles"]["premiere_alerte"].get(type_)
        if premiere:
            lignes.append(f"| {NOMS_TYPES[type_]} | " + ", ".join(f"`{k}` ({v})" for k, v in sorted(premiere.items())) + " |")
    lignes += ["", "## Seuils des règles", "", "| Paramètre | Valeur |", SEPARATEUR_DEUX_COLONNES] + [f"| `{k}` | {_n(v, 2).rstrip('0').rstrip(',')} |" for k, v in p["parametres_regles"].items()]
    return "\n".join(lignes) + "\n"


def ecrire(chemin_json: Path | None = None, chemin_md: Path | None = None) -> dict:
    chemin_json, chemin_md = chemin_json or JSON, chemin_md or MARKDOWN
    r = executer()
    chemin_json.write_text(json.dumps(r, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    chemin_md.write_text(markdown(r), encoding="utf-8", newline="\n")
    return r
