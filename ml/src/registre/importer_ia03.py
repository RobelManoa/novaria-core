"""De l'évaluation d'IA-03 (`ml/evaluation/`) au document `model_runs` : la trace d'un entraînement déjà fait.

`selection.json` et `resultat-test.json` portent tout ce que le registre demande : paramètres, métriques, empreinte du jeu,
révision du code, graine. Un résultat « rejeté » devient un run `rejected` (la trace reste, aucun fichier de modèle).
L'identifiant du run contient le début du SHA-256 de `selection.json` : refaire l'import ne crée pas de doublon.
"""

import json
from datetime import datetime

from entrainement import tracabilite
from registre import documents
from registre.registre import Registre, RegistreErreur
from registre.runs import RunDejaEnregistre


def identifiant(resultat: dict) -> str:
    return documents.valider_run_id(f"ia03-{resultat['candidat']}-{resultat['selection_sha256'][:10]}")


def parametres_du_run(resultat: dict) -> tuple[dict, dict]:
    """(params, metrics) du document : ce qui a été réglé, puis ce qui a été mesuré."""
    t = resultat["tracabilite"]
    params = {
        "usage": "detection", "candidat": resultat["candidat"], "libelle": resultat["libelle"],
        "hyperparametres": resultat["params"], "variante": resultat["variante"], "versions": t["versions"],
        "selection_sha256": resultat["selection_sha256"], "runs_d_entrainement": resultat["runs_d_entrainement"],
        "date": "lecture du test : l'entraînement n'a pas été daté séparément",
    }
    metrics = {
        "decision": resultat["decision"], "conditions": resultat["conditions"], "modele": resultat["modele"],
        "regle": resultat["regle"], "matrice_modele": resultat["matrice_modele"], "runs_du_test": resultat["runs_du_test"],
    }
    return params, metrics


def raison_du_rejet(resultat: dict) -> str:
    manquees = [f"{c['condition']} ({c['libelle']}) : {c['modele']}, exigé {c['exige']}" for c in resultat["conditions"] if not c["remplie"]]
    return "conditions manquées : " + " ; ".join(manquees)


def importer(registre: Registre) -> tuple[str, dict, bool]:
    """Écrit le run d'IA-03 dans le registre. Rend (run_id, document, créé) ; `créé` est faux si le run existait déjà."""
    resultat = json.loads(tracabilite.RESULTAT_TEST.read_text(encoding="utf-8"))
    run_id = identifiant(resultat)
    t = resultat["tracabilite"]
    params, metrics = parametres_du_run(resultat)
    try:
        registre.enregistrer_entrainement(
            run_id, git_sha=t["git_sha"], git_dirty=bool(t["code_modifie_non_commite"]), dataset_id=t["dataset_id"],
            dataset_sha256=t["dataset_sha256"], seed=t["seed"], params=params, metrics=metrics,
            created_at=datetime.fromisoformat(resultat["lu_le"]),
        )
    except RunDejaEnregistre:
        return run_id, registre.runs.obtenir(run_id), False
    if resultat["decision"] != "accepté":
        registre.rejeter(run_id, raison_du_rejet(resultat))
    elif not registre.runs.obtenir(run_id):
        raise RegistreErreur(f"{run_id} introuvable après son écriture")
    return run_id, registre.runs.obtenir(run_id), True
