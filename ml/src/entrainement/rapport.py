"""`ml/evaluation/resultats.md` : le tableau comparatif écrit à partir de `selection.json` et de `resultat-test.json`.

Aucun chiffre n'est tapé à la main : tout vient des deux fichiers de résultats. Les fichiers lus et écrits sont ceux du
module `tracabilite` (jamais un chemin reçu en paramètre).
"""

import json

from entrainement import tracabilite

VARIANTES = {"brut": "sortie brute", "confirme": "confirmation sur 2 fenêtres"}
EN_TETE = ("| | F1 macro | Rappel CONGESTED | Précision CONGESTED | Délai médian / max (min) | Épisodes manqués | Fausses alertes par tronçon et jour |\n"
           "|---|---|---|---|---|---|---|")


def _f(valeur, chiffres=3) -> str:
    return "–" if valeur is None else f"{valeur:.{chiffres}f}".replace(".", ",")


def _oui_non(valeur: bool, non: str = "non") -> str:
    return "oui" if valeur else non


def _json(valeur) -> str:
    return json.dumps(valeur, ensure_ascii=False)


def _delai(m: dict) -> str:
    return "–" if m["delai_median_min"] is None else f"{m['delai_median_min']:g} / {m['delai_max_min']}"


def _ligne(nom: str, m: dict) -> str:
    return (f"| {nom} | {_f(m['f1_macro'])} | {_f(m['rappel_congested'])} | {_f(m['precision_congested'])} | {_delai(m)} | "
            f"{m['episodes_manques']} / {m['episodes']} | {_f(m['fausses_alertes_par_troncon_et_jour'], 2)} |")


def _tracabilite(t: dict) -> list[str]:
    modifie = " (code modifié, non commité)" if t["code_modifie_non_commite"] else ""
    return ["# Résultats de la comparaison (IA-03)", "",
            "Fichier **généré** par `python3 scripts/dev/dev.py ml-train rapport` à partir de `selection.json` et de `resultat-test.json` : ne pas l'écrire à la main. Le choix argumenté est dans [comparaison.md](comparaison.md).", "",
            "> **Données simulées.** Un modèle entraîné sur le simulateur apprend le simulateur : ces résultats prouvent la chaîne, pas la précision en conditions réelles.", "",
            "## 1. Traçabilité", "", "| Champ | Valeur |", "|---|---|",
            f"| Jeu | `{t['dataset_id']}`, empreinte `{t['dataset_sha256']}` |", f"| Graine | {t['seed']} |",
            f"| Révision du code | `{t['git_sha']}`{modifie} |",
            "| Versions | " + ", ".join(f"{k} {v}" for k, v in t["versions"].items()) + " |", ""]


def _retenus(selection: dict) -> list[str]:
    lignes = ["## 2. Validation : réglage et choix", "", selection["regle_de_choix"], "", "### 2.1 Réglage retenu de chaque candidat, sur la validation", "", EN_TETE,
              _ligne("Règle de seuils (référence)", selection["reference_validation"])]
    for fiche in selection["candidats"].values():
        r = fiche["retenu"]
        if r:
            lignes.append(_ligne(f"{fiche['libelle']} ({VARIANTES[r['variante']]})", r["validation"]))
    lignes += ["", "| Candidat | Réglage retenu | Variante | Éligibles (brut) | Éligibles (confirmé) | Réglages essayés | Reproductible |", "|---|---|---|---|---|---|---|"]
    for fiche in selection["candidats"].values():
        essais, r = fiche["essais"], fiche["retenu"]
        reglage, variante = (_json(r["params"]), VARIANTES[r["variante"]]) if r else ("–", "–")
        reproductible = _oui_non(fiche.get("reproductible", False)) if r else "–"
        lignes.append(f"| {fiche['libelle']} | {reglage} | {variante} | "
                      f"{sum(e['eligible_brut'] for e in essais)} / {len(essais)} | {sum(e['eligible_confirme'] for e in essais)} / {len(essais)} | {len(essais)} | "
                      f"{reproductible} |")
    return lignes


def _reglages(selection: dict) -> list[str]:
    lignes = ["", "### 2.2 Tous les réglages essayés (brut)", "", "| Candidat | Réglage | F1 macro | Rappel CONGESTED | Fausses alertes par tronçon et jour | Éligible |", "|---|---|---|---|---|---|"]
    for nom, fiche in selection["candidats"].items():
        for e in fiche["essais"]:
            b = e["brut"]
            lignes.append(f"| {nom} | {_json(e['params'])} | {_f(b['f1_macro'])} | {_f(b['rappel_congested'])} | "
                          f"{_f(b['fausses_alertes_par_troncon_et_jour'], 2)} | {_oui_non(e['eligible_brut'])} |")
    return lignes


def _validation_croisee(selection: dict) -> list[str]:
    lignes = ["", "### 2.3 Validation croisée groupée par run (diagnostic : elle ne choisit rien)", "",
              "Trois plis sur entraînement et validation : chaque pli met de côté un run de **chaque** scénario. Moyenne ± écart-type des trois plis.", "",
              "| | F1 macro | Rappel CONGESTED | Fausses alertes par tronçon et jour |", "|---|---|---|---|"]
    for fiche in selection["candidats"].values():
        cv = fiche.get("validation_croisee_groupee")
        for cle, libelle in (("modele", fiche["libelle"]), ("regle", "Règle de seuils sur les mêmes plis")) if cv else ():
            r = cv[cle]
            lignes.append(f"| {libelle} | {_f(r['f1_macro']['moyenne'])} ± {_f(r['f1_macro']['ecart_type'])} | "
                          f"{_f(r['rappel_congested']['moyenne'])} ± {_f(r['rappel_congested']['ecart_type'])} | "
                          f"{_f(r['fausses_alertes_par_troncon_et_jour']['moyenne'], 2)} ± {_f(r['fausses_alertes_par_troncon_et_jour']['ecart_type'], 2)} |")
    return lignes


def _choix(selection: dict) -> list[str]:
    c = selection["choix"]
    raison = c["raison"][0].upper() + c["raison"][1:]
    detail = f", {VARIANTES[c['variante']]}, réglage {_json(c['params'])}" if c["candidat"] else ""
    return ["", "### 2.4 Choix", "", f"Candidat retenu : **{c['candidat'] or 'aucun'}**{detail}. {raison}.", ""]


def _test(test: dict | None) -> list[str]:
    if test is None:
        return ["## 3. Test", "", "Le test n'a pas encore été lu.", ""]
    lignes = ["## 3. Test (lu une seule fois)", "", f"Lu le {test['lu_le']} (UTC), après le choix : empreinte de `selection.json` `{test['selection_sha256']}`. "
              f"Runs du test : {', '.join(test['runs_du_test'])}.", "", EN_TETE, _ligne("Règle de seuils (référence)", test["regle"]),
              _ligne(f"{test['libelle']} ({VARIANTES[test['variante']]})", test["modele"]), "",
              "### 3.1 Conditions d'acceptation (cadrage ML, section 6)", "", "| N° | Condition | Modèle | Exigé | Remplie |", "|---|---|---|---|---|"]
    for x in test["conditions"]:
        lignes.append(f"| {x['condition']} | {x['libelle']} | {_f(x['modele'], 4)} | {x['exige']} | {_oui_non(x['remplie'], '**non**')} |")
    lignes += ["", f"**Décision : modèle {test['decision']}.**", "", "### 3.2 Matrice de confusion du modèle sur le test (ligne : état réel, colonne : état annoncé)", "",
               "| | FREE_FLOW | SLOW | CONGESTED |", "|---|---|---|---|"]
    for reel, ligne in test["matrice_modele"].items():
        lignes.append(f"| {reel} | {ligne['FREE_FLOW']} | {ligne['SLOW']} | {ligne['CONGESTED']} |")
    return lignes


def rediger(selection: dict, test: dict | None) -> str:
    lignes = (_tracabilite(selection["tracabilite"]) + _retenus(selection) + _reglages(selection)
              + _validation_croisee(selection) + _choix(selection) + _test(test))
    return "\n".join(lignes) + "\n"


def ecrire() -> str:
    """Écrit `tracabilite.RAPPORT` depuis `tracabilite.SELECTION` et, s'il existe, `tracabilite.RESULTAT_TEST`."""
    selection = json.loads(tracabilite.SELECTION.read_text(encoding="utf-8"))
    test = json.loads(tracabilite.RESULTAT_TEST.read_text(encoding="utf-8")) if tracabilite.RESULTAT_TEST.is_file() else None
    texte = rediger(selection, test)
    tracabilite.RAPPORT.write_text(texte, encoding="utf-8")
    return texte
