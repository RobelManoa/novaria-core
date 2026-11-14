"""Les trois étapes du pipeline : `evaluer`, `porte`, `enregistrer`."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pipeline
from entrainement import acceptation, candidats, evaluation, tracabilite
from jeu_entrainement import catalogue as cat
from pipeline import controles, decision
from pipeline.decision import Bloque
from preparation import donnees
from registre import format_lineaire
from registre.registre import Registre, RegistreErreur
from registre.runs import RunDejaEnregistre, RunStore
from stockage import ObjectStore, sha256


def configuration_figee() -> tuple[dict, dict, str]:
    """La sélection d'IA-03 et le résultat du test qui la cite : le pipeline n'entraîne que cette configuration, telle quelle.

    Il n'y a ni recherche de réglage, ni choix de candidat ici : l'empreinte de `selection.json` doit être celle que
    `resultat-test.json` a enregistrée. Un autre choix est une nouvelle sélection, donc un nouveau test (avenant du cadrage).
    """
    try:
        octets = tracabilite.SELECTION.read_bytes()
        choix = json.loads(octets.decode("utf-8"))
        resultat = json.loads(tracabilite.RESULTAT_TEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erreur:
        raise tracabilite.ControleDeSecurite(f"sélection ou résultat d'IA-03 illisible ({erreur})") from erreur
    if choix.get("etape") != "validation" or not choix.get("choix", {}).get("candidat"):
        raise tracabilite.ControleDeSecurite("selection.json ne désigne aucun candidat")
    if resultat.get("selection_sha256") != sha256(octets):
        raise tracabilite.ControleDeSecurite(
            "selection.json n'est plus celle dont resultat-test.json porte l'empreinte : une autre configuration demande un test neuf")
    return choix, resultat, sha256(octets)


def identifiant(candidat: str, selection_sha: str, git_sha: str | None, modifie: bool) -> str:
    return f"ia05-{candidat}-{selection_sha[:8]}-{(git_sha or 'sans-git')[:8]}" + ("-modifie" if modifie else "")


def evaluer(*, dossier_jeu: Path = donnees.DOSSIER_JEU, runs: RunStore, objets: ObjectStore, message=print, audit: bool = True,
            catalogue: tuple = cat.CATALOGUE) -> dict:
    """Entraîne la configuration figée, l'évalue sur le test, applique les contrôles, écrit `decision.json` et le run `trained`."""
    choix, enregistre, selection_sha = configuration_figee()
    s1 = controles.s1_jeu_intact(dossier_jeu, choix["tracabilite"]["dataset_sha256"])
    if not s1.ok:
        raise tracabilite.ControleDeSecurite(f"S1 : {s1.detail}")  # on ne lit pas le test d'un jeu douteux
    message(f"S1 : {s1.detail}")
    c = candidats.candidat(choix["choix"]["candidat"])
    params, variante = choix["choix"]["params"], choix["choix"]["variante"]
    train = donnees.charger("train", dossier_jeu)
    runs_train = [r.run_id for r in cat.par_ensemble(catalogue)[cat.TRAIN]]
    preparation = evaluation.preparer(train, runs_train)
    x, y = preparation.transformer(train, imputer=c.imputer)
    modele, avertissements = candidats.ajuster(c, params, x, y)
    message(f"Entraînement : {c.libelle}, réglage {params}")
    test = donnees.charger("test", dossier_jeu, evaluation_finale=True)
    _, predits = evaluation.predictions(modele, preparation, test, c.imputer)
    mesures_modele = evaluation.mesurer_predictions(test, predits, variante == "confirme")
    mesures_regle = evaluation.mesurer_la_regle(test)
    conditions = [x_.en_dict() for x_ in acceptation.conditions(mesures_modele, mesures_regle)]
    octets, erreur_d_export = None, None
    try:
        octets = format_lineaire.exporter(modele, preparation)
    except format_lineaire.FormatInvalide as erreur:
        erreur_d_export = str(erreur)
    info = tracabilite.tracabilite(choix["tracabilite"]["dataset_sha256"])
    recalcule = {**mesures_modele.en_dict(), "matrice": evaluation.matrice_de_confusion([ligne["label_state"] for ligne in test], predits)}
    securite = [
        s1,
        controles.s2_artefact_trace(octets, predits, lambda b: format_lineaire.ModeleLineaire.depuis_octets(b).predire(test)),
        controles.s3_format_sur(c.nom, octets, erreur_d_export),
        controles.s4_dependances() if audit else controles.Controle("S4", "dépendances ML sans vulnérabilité connue (pip-audit)", None, "audit désactivé : non vérifié", False),
        controles.s5_fiche_du_modele(c.nom),
        controles.t1_code_commite(info["code_modifie_non_commite"], info["git_sha"]),
        controles.r1_reproduction(recalcule, {**enregistre["modele"], "matrice": enregistre["matrice_modele"]}),
    ]
    securite_dicts = [s.en_dict() for s in securite]
    accepte, raisons = decision.decider(conditions, securite_dicts)
    run_id = identifiant(c.nom, selection_sha, info["git_sha"], info["code_modifie_non_commite"])
    document = {
        "pipeline_version": pipeline.VERSION, "run_id": run_id, "decision": "accepté" if accepte else "rejeté",
        "candidat": c.nom, "libelle": c.libelle, "params": params, "variante": variante, "selection_sha256": selection_sha,
        "tracabilite": info, "conditions": conditions, "securite": securite_dicts, "modele": mesures_modele.en_dict(),
        "regle": mesures_regle.en_dict(), "modele_sha256": sha256(octets) if octets else None,
        "avertissements_d_entrainement": avertissements, "runs_d_entrainement": runs_train,
        "runs_du_test": sorted({ligne["run_id"] for ligne in test}), "date": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    pipeline.DOSSIER.mkdir(parents=True, exist_ok=True)
    if octets:
        pipeline.MODELE_PREPARE.write_bytes(octets)
    elif pipeline.MODELE_PREPARE.exists():
        pipeline.MODELE_PREPARE.unlink()  # pas d'artefact : aucun reste d'une exécution précédente
    pipeline.DECISION.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        Registre(runs, objets).enregistrer_entrainement(
            run_id, git_sha=info["git_sha"] or "0" * 40, git_dirty=bool(info["code_modifie_non_commite"]), dataset_id=info["dataset_id"],
            dataset_sha256=info["dataset_sha256"], seed=info["seed"],
            params={"usage": "detection", "candidat": c.nom, "hyperparametres": params, "variante": variante, "versions": info["versions"],
                    "selection_sha256": selection_sha, "pipeline_version": pipeline.VERSION},
            metrics={"decision": document["decision"], "conditions": conditions, "securite": securite_dicts, "modele": document["modele"], "regle": document["regle"]},
        )
    except RunDejaEnregistre:
        message(f"Le run {run_id} existe déjà dans le registre : il n'est pas réécrit")
    for s in securite:
        message(f"  {s.code} {s.etat} : {s.libelle} ({s.detail})")
    for x_ in conditions:
        message(f"  {x_['condition']} {'remplie' if x_['remplie'] else 'MANQUÉE'} : {x_['libelle']} (modèle {x_['modele']}, exigé {x_['exige']})")
    message(f"Décision : modèle {document['decision']}")
    return decision.lire()


def porte(*, runs: RunStore, objets: ObjectStore, message=print) -> bool:
    """La porte : rend `True` si le modèle est accepté ; sinon écrit le run `rejected` (la trace, jamais un fichier) et rend `False`."""
    d = decision.lire()
    pipeline.RAPPORT_MD.write_text(decision.rapport(d), encoding="utf-8")
    if d["decision"] == "accepté":
        message(f"Porte ouverte : {d['run_id']} remplit toutes les conditions et tous les contrôles bloquants")
        return True
    try:
        Registre(runs, objets).rejeter(d["run_id"], "; ".join(d["raisons"]))
    except RegistreErreur:
        message(f"Le run {d['run_id']} était déjà traité dans le registre")
    message(f"Porte FERMÉE : modèle sous le seuil ou non conforme, il n'est pas enregistré ({len(d['raisons'])} raison(s))")
    for raison in d["raisons"]:
        message(f"  - {raison}")
    return False


def enregistrer(*, runs: RunStore, objets: ObjectStore, message=print) -> dict:
    """Après la porte seulement : promeut le modèle préparé. Refuse si la décision n'est pas « accepté » ou si le fichier a changé."""
    d = decision.lire()
    if d["decision"] != "accepté":
        raise Bloque(f"{d['run_id']} : décision « {d['decision']} », modèle non enregistré")
    if not pipeline.MODELE_PREPARE.is_file():
        raise tracabilite.ControleDeSecurite("aucun modèle préparé à enregistrer")
    octets = pipeline.MODELE_PREPARE.read_bytes()
    if sha256(octets) != d["modele_sha256"]:
        raise tracabilite.ControleDeSecurite("le modèle préparé n'a plus l'empreinte de la décision (modifié entre les étapes)")
    run = Registre(runs, objets).promouvoir(d["run_id"], octets)
    message(f"Modèle enregistré et en service : {d['run_id']} (SHA-256 {run['model_sha256']})")
    return run
