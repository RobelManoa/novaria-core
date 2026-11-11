"""`ml/evaluation/resultats.md` : le tableau comparatif écrit à partir de `selection.json` et de `resultat-test.json`.

Aucun chiffre n'est tapé à la main : tout vient des deux fichiers de résultats.
"""

import json
from pathlib import Path

from entrainement import tracabilite


def _f(valeur, chiffres=3) -> str:
    return "–" if valeur is None else f"{valeur:.{chiffres}f}".replace(".", ",")


VARIANTES = {"brut": "sortie brute", "confirme": "confirmation sur 2 fenêtres"}


def _delai(m: dict) -> str:
    return "–" if m["delai_median_min"] is None else f"{m['delai_median_min']:g} / {m['delai_max_min']}"


def _ligne(nom: str, m: dict) -> str:
    return (f"| {nom} | {_f(m['f1_macro'])} | {_f(m['rappel_congested'])} | {_f(m['precision_congested'])} | {_delai(m)} | "
            f"{m['episodes_manques']} / {m['episodes']} | {_f(m['fausses_alertes_par_troncon_et_jour'], 2)} |")


EN_TETE = ("| | F1 macro | Rappel CONGESTED | Précision CONGESTED | Délai médian / max (min) | Épisodes manqués | Fausses alertes par tronçon et jour |\n"
           "|---|---|---|---|---|---|---|")


def rediger(selection: dict, test: dict | None) -> str:
    t = selection["tracabilite"]
    lignes = ["# Résultats de la comparaison (IA-03)", "",
              "Fichier **généré** par `python3 scripts/dev/dev.py ml-train rapport` à partir de `selection.json` et de `resultat-test.json` : ne pas l'écrire à la main. Le choix argumenté est dans [comparaison.md](comparaison.md).", "",
              "> **Données simulées.** Un modèle entraîné sur le simulateur apprend le simulateur : ces résultats prouvent la chaîne, pas la précision en conditions réelles.", "",
              "## 1. Traçabilité", "", "| Champ | Valeur |", "|---|---|",
              f"| Jeu | `{t['dataset_id']}`, empreinte `{t['dataset_sha256']}` |", f"| Graine | {t['seed']} |",
              f"| Révision du code | `{t['git_sha']}`" + (" (code modifié, non commité)" if t["code_modifie_non_commite"] else "") + " |",
              "| Versions | " + ", ".join(f"{k} {v}" for k, v in t["versions"].items()) + " |", ""]
    lignes += ["## 2. Validation : réglage et choix", "", selection["regle_de_choix"], "", "### 2.1 Réglage retenu de chaque candidat, sur la validation", "", EN_TETE,
               _ligne("Règle de seuils (référence)", selection["reference_validation"])]
    for nom, fiche in selection["candidats"].items():
        if fiche["retenu"]:
            r = fiche["retenu"]
            lignes.append(_ligne(f"{fiche['libelle']} ({VARIANTES[r['variante']]})", r["validation"]))
    lignes += ["", "| Candidat | Réglage retenu | Variante | Éligibles (brut) | Éligibles (confirmé) | Réglages essayés | Reproductible |", "|---|---|---|---|---|---|---|"]
    for nom, fiche in selection["candidats"].items():
        essais = fiche["essais"]
        r = fiche["retenu"]
        lignes.append(f"| {fiche['libelle']} | {json.dumps(r['params'], ensure_ascii=False) if r else '–'} | {VARIANTES[r['variante']] if r else '–'} | "
                      f"{sum(e['eligible_brut'] for e in essais)} / {len(essais)} | {sum(e['eligible_confirme'] for e in essais)} / {len(essais)} | {len(essais)} | "
                      f"{'–' if r is None else ('oui' if fiche.get('reproductible') else 'non')} |")
    lignes += ["", "### 2.2 Tous les réglages essayés (brut)", "", "| Candidat | Réglage | F1 macro | Rappel CONGESTED | Fausses alertes par tronçon et jour | Éligible |", "|---|---|---|---|---|---|"]
    for nom, fiche in selection["candidats"].items():
        for e in fiche["essais"]:
            lignes.append(f"| {nom} | {json.dumps(e['params'], ensure_ascii=False)} | {_f(e['brut']['f1_macro'])} | {_f(e['brut']['rappel_congested'])} | "
                          f"{_f(e['brut']['fausses_alertes_par_troncon_et_jour'], 2)} | {'oui' if e['eligible_brut'] else 'non'} |")
    lignes += ["", "### 2.3 Validation croisée groupée par run (diagnostic : elle ne choisit rien)", "",
               "Trois plis sur entraînement et validation : chaque pli met de côté un run de **chaque** scénario. Moyenne ± écart-type des trois plis.", "",
               "| | F1 macro | Rappel CONGESTED | Fausses alertes par tronçon et jour |", "|---|---|---|---|"]
    for nom, fiche in selection["candidats"].items():
        cv = fiche.get("validation_croisee_groupee")
        if cv:
            for cle, libelle in (("modele", fiche["libelle"]), ("regle", "Règle de seuils sur les mêmes plis")):
                r = cv[cle]
                lignes.append(f"| {libelle} | {_f(r['f1_macro']['moyenne'])} ± {_f(r['f1_macro']['ecart_type'])} | "
                              f"{_f(r['rappel_congested']['moyenne'])} ± {_f(r['rappel_congested']['ecart_type'])} | "
                              f"{_f(r['fausses_alertes_par_troncon_et_jour']['moyenne'], 2)} ± {_f(r['fausses_alertes_par_troncon_et_jour']['ecart_type'], 2)} |")
    c = selection["choix"]
    raison = c["raison"][0].upper() + c["raison"][1:]
    lignes += ["", "### 2.4 Choix", "", f"Candidat retenu : **{c['candidat'] or 'aucun'}**" + (f", {VARIANTES[c['variante']]}, réglage {json.dumps(c['params'], ensure_ascii=False)}" if c["candidat"] else "") + f". {raison}.", ""]
    if test is None:
        lignes += ["## 3. Test", "", "Le test n'a pas encore été lu.", ""]
        return "\n".join(lignes) + "\n"
    lignes += ["## 3. Test (lu une seule fois)", "", f"Lu le {test['lu_le']} (UTC), après le choix : empreinte de `selection.json` `{test['selection_sha256']}`. "
               f"Runs du test : {', '.join(test['runs_du_test'])}.", "", EN_TETE, _ligne("Règle de seuils (référence)", test["regle"]),
               _ligne(f"{test['libelle']} ({VARIANTES[test['variante']]})", test["modele"]), "",
               "### 3.1 Conditions d'acceptation (cadrage ML, section 6)", "", "| N° | Condition | Modèle | Exigé | Remplie |", "|---|---|---|---|---|"]
    for x in test["conditions"]:
        lignes.append(f"| {x['condition']} | {x['libelle']} | {_f(x['modele'], 4)} | {x['exige']} | {'oui' if x['remplie'] else '**non**'} |")
    lignes += ["", f"**Décision : modèle {test['decision']}.**", "", "### 3.2 Matrice de confusion du modèle sur le test (ligne : état réel, colonne : état annoncé)", "",
               "| | FREE_FLOW | SLOW | CONGESTED |", "|---|---|---|---|"]
    for reel, ligne in test["matrice_modele"].items():
        lignes.append(f"| {reel} | {ligne['FREE_FLOW']} | {ligne['SLOW']} | {ligne['CONGESTED']} |")
    return "\n".join(lignes) + "\n"


def ecrire(selection_json: Path = tracabilite.SELECTION, test_json: Path = tracabilite.RESULTAT_TEST, sortie: Path = tracabilite.RAPPORT) -> str:
    selection = json.loads(selection_json.read_text(encoding="utf-8"))
    test = json.loads(test_json.read_text(encoding="utf-8")) if test_json.is_file() else None
    texte = rediger(selection, test)
    sortie.write_text(texte, encoding="utf-8")
    return texte
