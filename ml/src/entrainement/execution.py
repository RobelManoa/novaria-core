"""Les trois étapes : `validation` (réglage, validation croisée, choix), `test` (une seule lecture), `rapport` (tableaux)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from entrainement import acceptation, candidats, evaluation, selection, tracabilite
from jeu_entrainement import catalogue as cat
from preparation import donnees

REGLE_DE_CHOIX = (
    "Au plus 12 réglages par candidat, mesurés sur la validation. Un réglage est éligible si ses fausses alertes restent sous "
    "0,10 par tronçon et par jour (A5) ; sinon sa variante avec confirmation sur 2 fenêtres est jugée. Le réglage retenu a le "
    "meilleur F1 macro de validation parmi les éligibles. Entre candidats : meilleur F1 macro de validation, le plus simple à "
    "moins de 0,002. La validation croisée groupée par run ne choisit rien."
)


def etape_validation(dossier: Path = donnees.DOSSIER_JEU, message=print, catalogue: tuple = cat.CATALOGUE) -> dict:
    """Réglage, validation croisée et choix ; écrit `tracabilite.SELECTION`. Le dossier du jeu n'est que lu."""
    empreinte = tracabilite.exiger_le_jeu_intact(dossier)
    message(f"S1 : jeu intact ({empreinte[:12]}…)")
    train, validation = donnees.charger("train", dossier), donnees.charger("validation", dossier)
    par = cat.par_ensemble(catalogue)
    runs_train = [r.run_id for r in par[cat.TRAIN]]
    reference_validation = evaluation.mesurer_la_regle(validation)
    message(f"Règle de référence, validation : F1 macro {reference_validation.f1_macro:.4f}")
    runs = [(r.run_id, r.scenario_id) for r in (*par[cat.TRAIN], *par[cat.VALIDATION])]
    resultat = {"etape": "validation", "regle_de_choix": REGLE_DE_CHOIX, "tracabilite": tracabilite.tracabilite(empreinte),
                "reference_validation": reference_validation.en_dict(), "candidats": {}}
    retenus = {}
    for c in candidats.CANDIDATS:
        message(f"{c.libelle} : {len(c.grille)} réglages")
        essais = selection.essayer_la_grille(c, train, validation, runs_train, message)
        retenu = selection.retenir(essais)
        retenus[c.nom] = retenu
        fiche = {"libelle": c.libelle, "essais": [e.en_dict() for e in essais], "retenu": None}
        if retenu is not None:
            fiche["retenu"] = {"indice": retenu.essai.indice, "params": retenu.essai.params, "variante": retenu.variante,
                               "validation": retenu.mesures.en_dict()}
            fiche["reproductible"] = _reproductible(c, retenu, train, validation, runs_train)
            message(f"  retenu : {retenu.essai.params} ({retenu.variante}), F1 macro de validation {retenu.mesures.f1_macro:.4f}, reproductible : {fiche['reproductible']}")
            fiche["validation_croisee_groupee"] = selection.validation_croisee_groupee(c, retenu, train + validation, runs)
        else:
            message("  aucun réglage éligible")
        resultat["candidats"][c.nom] = fiche
    nom, raison = selection.choisir_le_candidat(retenus)
    resultat["choix"] = {"candidat": nom, "variante": retenus[nom].variante if nom else None,
                        "params": retenus[nom].essai.params if nom else None, "raison": raison}
    message(f"Choix : {nom} — {raison}")
    tracabilite.SELECTION.parent.mkdir(parents=True, exist_ok=True)
    tracabilite.SELECTION.write_text(json.dumps(resultat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return resultat


def _reproductible(c, retenu, train, validation, runs_train) -> bool:
    """Deux entraînements identiques (même graine, mêmes données) donnent les mêmes prédictions et les mêmes mesures."""
    sorties = []
    for _ in range(2):
        preparation = evaluation.preparer(train, runs_train)
        x, y = preparation.transformer(train, imputer=c.imputer)
        modele, _ = candidats.ajuster(c, retenu.essai.params, x, y)
        _, predits = evaluation.predictions(modele, preparation, validation, c.imputer)
        sorties.append((predits, evaluation.mesurer_predictions(validation, predits, retenu.variante == "confirme").en_dict()))
    return sorties[0] == sorties[1]


def etape_test(dossier: Path = donnees.DOSSIER_JEU, message=print, catalogue: tuple = cat.CATALOGUE) -> dict:
    """Lit le test **une seule fois**, pour le candidat choisi et pour la règle ; lit `tracabilite.SELECTION`, écrit `tracabilite.RESULTAT_TEST`."""
    if tracabilite.RESULTAT_TEST.exists():
        raise tracabilite.ControleDeSecurite(
            f"{tracabilite.RESULTAT_TEST.name} existe : le test a déjà été lu. Un second essai est un avenant du cadrage (section 12), pas une relance")
    if not tracabilite.SELECTION.is_file():
        raise tracabilite.ControleDeSecurite("selection.json absent : faire d'abord l'étape validation (le choix précède la lecture du test)")
    choix = json.loads(tracabilite.SELECTION.read_text(encoding="utf-8"))
    if choix.get("etape") != "validation" or choix["choix"]["candidat"] is None:
        raise tracabilite.ControleDeSecurite("selection.json ne désigne aucun candidat : rien à évaluer sur le test")
    empreinte = tracabilite.exiger_le_jeu_intact(dossier, choix["tracabilite"]["dataset_sha256"])
    message(f"S1 : jeu intact et identique à celui de la sélection ({empreinte[:12]}…)")
    c = candidats.candidat(choix["choix"]["candidat"])
    params, confirmation = choix["choix"]["params"], choix["choix"]["variante"] == "confirme"
    train = donnees.charger("train", dossier)
    runs_train = [r.run_id for r in cat.par_ensemble(catalogue)[cat.TRAIN]]
    preparation = evaluation.preparer(train, runs_train)
    x, y = preparation.transformer(train, imputer=c.imputer)
    modele, avertissements = candidats.ajuster(c, params, x, y)
    message("Lecture du test (une seule fois)…")
    test = donnees.charger("test", dossier, evaluation_finale=True)
    _, predits = evaluation.predictions(modele, preparation, test, c.imputer)
    vrais = [ligne["label_state"] for ligne in test]
    mesures_modele = evaluation.mesurer_predictions(test, predits, confirmation)
    mesures_regle = evaluation.mesurer_la_regle(test)
    liste = acceptation.conditions(mesures_modele, mesures_regle)
    resultat = {
        "etape": "test",
        "lu_le": datetime.now(UTC).isoformat(timespec="seconds"),
        "selection_sha256": tracabilite.sha256_fichier(tracabilite.SELECTION),
        "tracabilite": tracabilite.tracabilite(empreinte),
        "candidat": c.nom, "libelle": c.libelle, "params": params, "variante": choix["choix"]["variante"],
        "avertissements_d_entrainement": avertissements,
        "runs_d_entrainement": runs_train,
        "runs_du_test": sorted({ligne["run_id"] for ligne in test}),
        "modele": mesures_modele.en_dict(),
        "regle": mesures_regle.en_dict(),
        "matrice_modele": evaluation.matrice_de_confusion(vrais, predits),
        "conditions": [x.en_dict() for x in liste],
        "decision": "accepté" if acceptation.accepte(liste) else "rejeté",
    }
    tracabilite.RESULTAT_TEST.write_text(json.dumps(resultat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for x_ in liste:
        message(f"  {x_.numero} {'remplie' if x_.remplie else 'MANQUÉE'} : {x_.libelle} (modèle {x_.modele if x_.modele is None else round(x_.modele, 4)}, exigé {x_.exige})")
    message(f"Décision : modèle {resultat['decision']}")
    return resultat

