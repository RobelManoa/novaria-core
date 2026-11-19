"""Exécute la campagne d'IA-10 et écrit `ml/evaluation/prevision.json` et `ml/evaluation/prevision-resultats.md`.

Ordre, sans retour en arrière : 1) découpage dans l'ordre du temps (70 % / 15 % / 15 %, délai de garde de 30 minutes) ;
2) pour chaque horizon, réglage de Ridge et d'HistGradientBoosting sur la **validation** ; 3) lecture du **test**, une fois,
pour les trois références et les deux modèles choisis ; 4) les mêmes méthodes sur trois runs simulés, sans réapprendre.
"""

import json
import time
from pathlib import Path

import numpy as np

from jeu_entrainement import catalogue as cat
from jeu_entrainement.catalogue import RunSpec
from jeu_entrainement.simulation import RACINE
from prevision import HORIZONS_MIN, HORIZONS_PAS, MPH_EN_KMH, PAS_MIN, evaluation, modeles, references, variables
from prevision.donnees import Serie
from preparation import decoupage

DOSSIER = RACINE / "ml" / "evaluation"
JSON = DOSSIER / "prevision.json"
MARKDOWN = DOSSIER / "prevision-resultats.md"
PARTS = (0.70, 0.15, 0.15)
GARDE_MIN = max(HORIZONS_MIN)
PAS_APPRENTISSAGE = 3  # un instant d'apprentissage sur trois (un par quart d'heure) : 1,7 million d'exemples au lieu de 5
HEURE = 3600
SIMULES = (
    ("ia10-calme-s401", "journee-calme", 401, "08:00", 6 * HEURE),
    ("ia10-pointe-s402", "heure-de-pointe", 402, "05:30", 6 * HEURE),
    ("ia10-incident-s403", "incident-ponctuel", 403, "06:00", 6 * HEURE),
)
NOMS_METHODES = {"persistance": "Persistance", "moyenne_glissante": "Moyenne glissante (1 h)", "naif_saisonnier": "Naïf saisonnier (veille)",
                 "ridge": "Ridge", "hist_gradient_boosting": "HistGradientBoosting"}
MODELES = tuple(modeles.FABRIQUES)


def _lignes(brut, rempli, instants_ms, t, horizon_pas):
    x = variables.matrice(brut, rempli, instants_ms, t)
    return x, variables.reponses(brut, t, horizon_pas)


def _prevoir(modele, x: np.ndarray) -> np.ndarray:
    return x[:, 0] + modele.predict(x)


def _etape(texte: str, debut: float, progres) -> None:
    progres(f"[{time.time() - debut:6.0f} s] {texte}")


def _jours(instants_ms: np.ndarray, t: np.ndarray, capteurs: int) -> np.ndarray:
    return np.repeat(instants_ms[t] // variables.JOUR_MS, capteurs)


def evaluer_metr_la(serie: Serie, progres=print, pas_apprentissage: int = PAS_APPRENTISSAGE) -> tuple[dict, dict]:
    """Rend les résultats et les modèles choisis (`{horizon_pas: {nom: modèle}}`), gardés en mémoire pour le run simulé."""
    debut = time.time()
    brut, instants = serie.vitesses, serie.instants_ms
    partition = decoupage.decouper_dans_l_ordre_du_temps([int(i) for i in instants], PARTS, GARDE_MIN)
    parties = {nom: np.array(sorted(partition[nom])) for nom in (cat.TRAIN, cat.VALIDATION, cat.TEST)}
    premier = variables.DEBUT_MIN
    parties = {nom: idx[idx >= premier] for nom, idx in parties.items()}
    apprentissage = parties[cat.TRAIN][::pas_apprentissage]
    valeur_initiale = float(np.nanmean(brut[parties[cat.TRAIN]]))
    rempli = variables.remplir(brut, valeur_initiale)
    capteurs = brut.shape[1]
    resultats: dict = {"horizons": {}, "donnees": {
        "pas": serie.pas, "capteurs": capteurs, "manquantes": float(np.isnan(brut).mean()),
        "parties": {nom: {"pas": int(len(idx)), "debut": _iso(instants[idx[0]]), "fin": _iso(instants[idx[-1]])} for nom, idx in parties.items()},
        "ecartes_par_la_garde": len(partition["ecartes"]), "garde_min": GARDE_MIN, "exemples_apprentissage": int(len(apprentissage) * capteurs),
    }}
    choisis: dict[int, dict] = {}
    _etape(f"données : {serie.pas} pas, {capteurs} capteurs ; apprentissage {len(apprentissage)} pas (un sur {pas_apprentissage})", debut, progres)

    x_apprentissage = {h: _lignes(brut, rempli, instants, apprentissage, h) for h in HORIZONS_PAS}
    for h in HORIZONS_PAS:
        minutes = h * PAS_MIN
        xa, ya = x_apprentissage[h]
        garde = ~np.isnan(ya)
        xa, cible = xa[garde], (ya - xa[:, 0])[garde]
        t_val = parties[cat.VALIDATION][parties[cat.VALIDATION] + h < serie.pas]  # le dernier pas n'a pas de réponse
        t_test = parties[cat.TEST][parties[cat.TEST] + h < serie.pas]
        xv, yv = _lignes(brut, rempli, instants, t_val, h)
        xt, yt = _lignes(brut, rempli, instants, t_test, h)
        jour_test = _jours(instants, t_test, capteurs)
        refs_v = references.calculer(brut, rempli, t_val, h)
        refs_t = references.calculer(brut, rempli, t_test, h)
        bloc: dict = {"validation": {}, "test": {}, "reglages": {}}
        previsions_test: dict[str, np.ndarray] = {}
        for nom in references.NOMS:
            bloc["validation"][nom] = evaluation.metriques(refs_v[nom], yv)
            bloc["test"][nom] = evaluation.metriques(refs_t[nom], yt)
            previsions_test[nom] = refs_t[nom]
        choisis[h] = {}
        for nom, (fabrique, grille) in modeles.FABRIQUES.items():
            essais = []
            meilleur = None
            for params in grille:
                modele = fabrique(params).fit(xa, cible)
                m = evaluation.metriques(_prevoir(modele, xv), yv)
                essais.append({"params": params, "mae_validation": m["mae"], "rmse_validation": m["rmse"]})
                _etape(f"horizon {minutes} min, {nom} {params} : MAE validation {m['mae']:.3f}", debut, progres)
                if meilleur is None or m["mae"] < meilleur[0]:
                    meilleur = (m["mae"], params, modele)
            _, params, modele = meilleur
            choisis[h][nom] = modele
            prevision = _prevoir(modele, xt)
            previsions_test[nom] = prevision
            bloc["validation"][nom] = {"mae": meilleur[0], "rmse": next(e["rmse_validation"] for e in essais if e["params"] == params), "n": int((~np.isnan(yv)).sum())}
            bloc["test"][nom] = evaluation.metriques(prevision, yt)
            bloc["reglages"][nom] = {"choisi": params, "essais": essais}
        bloc["meilleur_modele"] = min(MODELES, key=lambda n: bloc["validation"][n]["mae"])
        disponibles = [n for n in references.NOMS if refs_t[n] is not None]
        bloc["meilleure_reference"] = min(disponibles, key=lambda n: bloc["test"][n]["mae"])
        sommes = {n: evaluation.somme_par_jour(previsions_test[n], yt, jour_test) for n in (*disponibles, *MODELES)}
        nombre = sommes[bloc["meilleur_modele"]][1]
        bloc["ecarts"] = {n: evaluation.ecart_de_mae(sommes[bloc["meilleur_modele"]][0], sommes[n][0], nombre) for n in disponibles}
        resultats["horizons"][str(minutes)] = bloc
    _etape("METR-LA terminé", debut, progres)
    return resultats, choisis


def _iso(ms: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(ms) / 1000))


def evaluer_simule(series: list[Serie], choisis: dict, progres=print) -> dict:
    """Les méthodes (modèles déjà appris sur METR-LA, sans réapprentissage) sur des runs simulés, exemples de tous les runs réunis."""
    sortie: dict = {"runs": [s.nom for s in series], "horizons": {}, "par_run": {}}
    valeur_initiale = 25.0
    for h in HORIZONS_PAS:
        minutes = h * PAS_MIN
        reel, prev = [], {n: [] for n in (*references.NOMS, *MODELES)}
        applicable = True
        for serie in series:
            brut = serie.vitesses
            rempli = variables.remplir(brut, valeur_initiale)
            t = np.arange(variables.DEBUT_MIN, serie.pas - h)
            x, y = _lignes(brut, rempli, serie.instants_ms, t, h)
            refs = references.calculer(brut, rempli, t, h)
            for nom in references.NOMS:
                if refs[nom] is None:
                    applicable = False
                else:
                    prev[nom].append(refs[nom])
            for nom in MODELES:
                prev[nom].append(_prevoir(choisis[h][nom], x))
            reel.append(y)
            sortie["par_run"].setdefault(serie.nom, {})[str(minutes)] = {
                "persistance": evaluation.metriques(refs["persistance"], y), "ridge": evaluation.metriques(_prevoir(choisis[h]["ridge"], x), y),
                "hist_gradient_boosting": evaluation.metriques(_prevoir(choisis[h]["hist_gradient_boosting"], x), y),
            }
        y_tous = np.concatenate(reel)
        bloc = {"n": int((~np.isnan(y_tous)).sum()), "vitesse_reelle_moyenne_mph": float(np.nanmean(y_tous)), "methodes": {}}
        for nom, liste in prev.items():
            if nom == "naif_saisonnier" and not applicable:
                bloc["methodes"][nom] = None
            else:
                bloc["methodes"][nom] = evaluation.metriques(np.concatenate(liste), y_tous)
        sortie["horizons"][str(minutes)] = bloc
    progres("run simulé terminé")
    return sortie


def series_simulees() -> list[Serie]:
    from anomalies import campagne
    from prevision.donnees import serie_depuis_un_run

    series = []
    for run_id, scenario, graine, debut, duree in SIMULES:
        banc = campagne.executer(RunSpec(run_id, scenario, graine, "evaluation", debut, duree), campagne.EVALUATION)
        series.append(serie_depuis_un_run(banc))
    return series


def executer(chemin: Path | None = None, progres=print) -> dict:
    from prevision import donnees, source

    serie = donnees.charger_metr_la(source.verifier(chemin))
    resultats, choisis = evaluer_metr_la(serie, progres)
    resultats["simule"] = evaluer_simule(series_simulees(), choisis, progres)
    resultats["source"] = {"fichier": source.FICHIER, "sha256": source.SHA256, "taille_octets": source.TAILLE_OCTETS, "unite": "mph", "mph_en_kmh": MPH_EN_KMH}
    resultats["protocole"] = {"parts": PARTS, "garde_min": GARDE_MIN, "pas_apprentissage": PAS_APPRENTISSAGE, "tirages_ic": evaluation.TIRAGES,
                              "runs_simules": [{"run": r, "scenario": s, "graine": g, "debut": d, "duree_s": u} for r, s, g, d, u in SIMULES]}
    return resultats


# --------------------------------------------------------------------------- Markdown
def _n(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def _cellule(m: dict | None) -> str:
    return "non applicable" if m is None else f"{_n(m['mae'])} / {_n(m['rmse'])}"


def markdown(r: dict) -> str:
    d, h = r["donnees"], r["horizons"]
    ordre = (*references.NOMS, *MODELES)
    ligne = ["# Prévision de vitesse : résultats (IA-10)", "",
             "Fichier **généré** par `python3 scripts/dev/dev.py ml-prevision evaluer` (ne pas modifier à la main) ; le choix argumenté et la limite de validité sont dans [`prevision-comparaison.md`](prevision-comparaison.md).", "",
             "## Données et découpage", "",
             f"- METR-LA : {d['pas']} pas de {PAS_MIN} minutes, {d['capteurs']} capteurs, {_n(100 * d['manquantes'], 1)} % de mesures manquantes (vitesse 0 dans le fichier). Fiche : [PROVENANCE.md](../../data/datasets/metr-la/PROVENANCE.md).",
             f"- Découpage dans l'ordre du temps (70 % / 15 % / 15 %), délai de garde de {d['garde_min']} minutes ({d['ecartes_par_la_garde']} pas écartés) :", "",
             "| Partie | Pas | Début | Fin |", "|---|---|---|---|"]
    for nom, titre in ((cat.TRAIN, "Apprentissage"), (cat.VALIDATION, "Validation"), (cat.TEST, "Test")):
        p = d["parties"][nom]
        ligne.append(f"| {titre} | {p['pas']} | {p['debut']} | {p['fin']} |")
    ligne += ["", f"Exemples d'apprentissage : {d['exemples_apprentissage']} (un instant sur {r['protocole']['pas_apprentissage']}, {d['capteurs']} capteurs). Unité : miles par heure (mph) ; 1 mph = {_n(MPH_EN_KMH, 3)} km/h.", "",
              "## Test sur METR-LA : MAE / RMSE (mph)", "", "| Méthode | " + " | ".join(f"{m} min" for m in h) + " |", "|---|" + "---|" * len(h)]
    for nom in ordre:
        ligne.append(f"| {NOMS_METHODES[nom]} | " + " | ".join(_cellule(h[m]["test"].get(nom)) for m in h) + " |")
    ligne += ["", "## Meilleur modèle contre les références", "",
              "Écart de MAE entre le meilleur modèle (choisi sur la validation) et chaque référence, avec l'intervalle à 95 % par rééchantillonnage de journées. Négatif : le modèle fait mieux.", "",
              "| Horizon | Meilleur modèle | Contre | Écart de MAE (mph) | Intervalle à 95 % | Bat la référence ? |", "|---|---|---|---|---|---|"]
    for m, bloc in h.items():
        for ref, e in bloc["ecarts"].items():
            verdict = "oui" if e["haut"] < 0 else ("non (pire)" if e["bas"] > 0 else "non établi")
            ligne.append(f"| {m} min | {NOMS_METHODES[bloc['meilleur_modele']]} | {NOMS_METHODES[ref]} | {_n(e['ecart_mae'], 3)} | [{_n(e['bas'], 3)} ; {_n(e['haut'], 3)}] | {verdict} |")
    ligne += ["", "## Réglages choisis sur la validation", "", "| Horizon | Modèle | Réglage | MAE validation (mph) |", "|---|---|---|---|"]
    for m, bloc in h.items():
        for nom in MODELES:
            reglage = ", ".join(f"{k} = {v}" for k, v in bloc["reglages"][nom]["choisi"].items())
            ligne.append(f"| {m} min | {NOMS_METHODES[nom]} | {reglage} | {_n(bloc['validation'][nom]['mae'], 3)} |")
    s = r["simule"]
    ligne += ["", "## Run simulé : MAE / RMSE (mph), modèles appris sur METR-LA, sans réapprentissage", "",
              f"Trois runs de 6 h ({', '.join(s['runs'])}), exemples réunis. Vitesses du simulateur converties de km/h en mph. **Limite de validité : voir [`prevision-comparaison.md`](prevision-comparaison.md).**", "",
              "| Méthode | " + " | ".join(f"{m} min" for m in s["horizons"]) + " |", "|---|" + "---|" * len(s["horizons"])]
    for nom in ordre:
        ligne.append(f"| {NOMS_METHODES[nom]} | " + " | ".join(_cellule(s["horizons"][m]["methodes"].get(nom)) for m in s["horizons"]) + " |")
    ligne.append("| Exemples mesurés | " + " | ".join(str(s["horizons"][m]["n"]) for m in s["horizons"]) + " |")
    ligne.append("| Vitesse réelle moyenne (mph) | " + " | ".join(_n(s["horizons"][m]["vitesse_reelle_moyenne_mph"], 1) for m in s["horizons"]) + " |")
    ligne += ["", "Biais moyen, prévision − réel (mph) : négatif, le modèle prévoit une vitesse plus basse que la réalité.", "",
              "| Méthode | " + " | ".join(f"{m} min" for m in s["horizons"]) + " |", "|---|" + "---|" * len(s["horizons"])]
    for nom in ("persistance", *MODELES):
        ligne.append(f"| {NOMS_METHODES[nom]} | " + " | ".join(_n(s["horizons"][m]["methodes"][nom]["biais"]) for m in s["horizons"]) + " |")
    ligne += ["", "## Biais du modèle sur METR-LA (test), pour comparaison", "", "| Méthode | " + " | ".join(f"{m} min" for m in h) + " |", "|---|" + "---|" * len(h)]
    for nom in ("persistance", *MODELES):
        ligne.append(f"| {NOMS_METHODES[nom]} | " + " | ".join(_n(h[m]["test"][nom]["biais"]) for m in h) + " |")
    return "\n".join(ligne) + "\n"


def ecrire(chemin_json: Path | None = None, chemin_md: Path | None = None, progres=print) -> dict:
    chemin_json, chemin_md = chemin_json or JSON, chemin_md or MARKDOWN
    r = executer(progres=progres)
    chemin_json.write_text(json.dumps(r, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    chemin_md.write_text(markdown(r), encoding="utf-8", newline="\n")
    return r
