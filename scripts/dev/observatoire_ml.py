"""La chaîne d'entraînement du modèle, en schéma vivant (onglet « Entraînement » de l'observatoire).

Comme la carte des services montre la pile **en direct**, cette carte montre la chaîne **hors ligne** : du simulateur au registre
des modèles. Chaque case lit **ce que les étapes ont réellement écrit** (manifeste du jeu, sélection, résultat du test, dernière
décision du pipeline) : rien n'est écrit à la main, une case dont le fichier manque est dite « absente », jamais « faite ».

Les étapes qui se rejouent en direct sont des commandes de `dev.py` (voir `observatoire_demos.py`) ; ce module ne lance rien.
Bibliothèque standard seulement.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JEU = ROOT / "data" / "datasets" / "novaria-congestion-v1"
EVALUATION = ROOT / "ml" / "evaluation"
DECISION = ROOT / "var" / "pipeline" / "decision.json"
POINTEUR = ROOT / "var" / "models" / "en-service.json"

# etat : ok (fait), alarme (refus voulu), touche (à relier), arret (rien trouvé)
COLONNES = 6


def _lire(chemin: Path) -> dict | None:
    try:
        document = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _pct(valeur) -> str:
    return "non disponible" if not isinstance(valeur, (int, float)) else f"{valeur:.3f}".replace(".", ",")


def _noeud(identifiant: str, colonne: int, ligne: int, libelle: str, role: str, entree: str, sortie: str, *, commande: str = "",
           demo: str | None = None, etat: str = "arret", sous: str = "", details: list[tuple[str, str]] | None = None) -> dict:
    return {"id": identifiant, "colonne": colonne, "ligne": ligne, "libelle": libelle, "role": role, "entree": entree, "sortie": sortie,
            "commande": commande, "demo": demo, "etat": etat, "sous": sous, "details": [{"nom": n, "valeur": v} for n, v in (details or [])]}


def carte(jeu: Path = JEU, evaluation: Path = EVALUATION, decision: Path = DECISION, pointeur: Path = POINTEUR) -> dict:
    manifeste = _lire(jeu / "manifest.json")
    selection = _lire(evaluation / "selection.json")
    test = _lire(evaluation / "resultat-test.json")
    verdict = _lire(decision)
    noeuds = []

    noeuds.append(_noeud(
        "simulateur", 0, 0, "Simulateur de trafic",
        "Fabrique des runs de trafic **simulé** avec leur **vérité terrain** : l'état voulu par le scénario, jamais la sortie de la règle de seuils (ADR-027).",
        "un scénario (journée calme, heure de pointe, incident) et une graine", "des mesures de capteurs, avec l'état voulu de chaque tronçon",
        commande="simulator/app.py run --scenario … --seed …", etat="ok", sous="données simulées",
        details=[("Scénarios", "journée calme, heure de pointe, incident ponctuel"), ("Reproductible", "même graine, mêmes messages"), ("Provenance", "SIMULATED : jamais présenté comme réel")]))

    if manifeste:
        runs = manifeste.get("runs", [])
        parts = {}
        for run in runs:
            parts[run.get("ensemble", "?")] = parts.get(run.get("ensemble", "?"), 0) + 1
        fichiers = manifeste.get("fichiers", {})
        lignes = sum(f.get("lignes", 0) for f in fichiers.values())
        noeuds.append(_noeud(
            "jeu", 1, 0, "Jeu d'entraînement v1",
            "Les runs sont rejoués dans le **moteur de fenêtres du traitement** (le même qu'en production) et écrits en Parquet : une ligne par minute et par tronçon, avec l'état voulu comme étiquette.",
            "12 runs du simulateur", "train.parquet, validation.parquet, test.parquet et un manifeste avec leurs empreintes SHA-256",
            commande="dev.py dataset-build", etat="ok", sous=f"{len(runs)} runs · {lignes:,} lignes".replace(",", " "),
            details=[("Identifiant", str(manifeste.get("dataset_id"))), ("Découpage par run", " · ".join(f"{k} : {v}" for k, v in sorted(parts.items()))),
                     ("Empreinte du jeu", str(manifeste.get("empreinte_du_jeu", ""))[:16] + "…"), ("Origine", str((manifeste.get("origine") or {}).get("source_type", "?")))]))
    else:
        noeuds.append(_noeud("jeu", 0, 1, "Jeu d'entraînement v1", "Le jeu n'est pas sur ce poste (il n'est pas dans Git, ADR-027).", "12 runs du simulateur",
                             "train, validation, test", commande="dev.py dataset-build", etat="arret", sous="absent : dev.py dataset-build"))

    noeuds.append(_noeud(
        "preparation", 2, 0, "Préparation",
        "Découpe **par run et par scénario** (jamais au hasard) et ne garde que les variables permises : **aucune fuite du futur**, aucun identifiant, aucun calendrier. Le test n'est pas lu.",
        "le jeu v1", "des variables vérifiées et un découpage d'empreinte connue",
        commande="dev.py preparation-check", demo="ent-preparation", etat="ok" if manifeste else "arret", sous="prête : jeu présent" if manifeste else "jeu absent",
        details=[("Découpage", "6 runs d'entraînement, 3 de validation, 3 de test"), ("Garde-fou", "aucune variable qui connaît le futur")]))

    noeuds.append(_noeud(
        "reference", 2, 1, "Référence à battre",
        "Mesure la **règle de seuils avec hystérésis** (ADR-028) sur l'entraînement et la validation. Un modèle appris ne vaut que s'il fait mieux : c'est le barème.",
        "le jeu v1", "F1 macro, rappel de CONGESTED, délai de détection, fausses alertes par tronçon et par jour",
        commande="dev.py reference-mesure", demo="ent-reference", etat="ok" if manifeste else "arret", sous="prête : règle de seuils" if manifeste else "jeu absent",
        details=[("Pourquoi", "sans référence simple, un score ne dit rien"), ("Test", "illisible à cette étape")]))

    if selection:
        choix = selection.get("choix") or {}
        candidats = selection.get("candidats") or {}
        essais = sum(len(c.get("essais", [])) for c in candidats.values())
        noeuds.append(_noeud(
            "entrainement", 3, 0, "Entraînement",
            "Entraîne deux candidats (**régression logistique** et **gradient boosting**), règle chacun sur la **validation** (au plus 12 réglages) et choisit : le meilleur F1 macro parmi ceux dont les fausses alertes restent sous le budget.",
            "variables de l'entraînement, étiquettes de la vérité terrain", "un candidat choisi, avec son réglage (selection.json)",
            commande="dev.py ml-train validation (réécrit selection.json : non rejoué en direct)", etat="ok",
            sous=f"choisi : {choix.get('candidat', '?')} · {essais} réglages essayés",
            details=[("Candidats", ", ".join(sorted(candidats))), ("Réglage retenu", json.dumps(choix.get("params", {}), ensure_ascii=False)), ("Raison", str(choix.get("raison", ""))),
                     ("Règle de choix", "décidée avant l'entraînement (cadrage ML)")]))
    else:
        noeuds.append(_noeud("entrainement", 2, 0, "Entraînement", "Entraîne deux candidats et les règle sur la validation.", "le jeu", "selection.json",
                             commande="dev.py ml-train validation", etat="arret", sous="aucune sélection trouvée"))

    if test:
        modele = test.get("modele") or {}
        noeuds.append(_noeud(
            "evaluation", 3, 1, "Évaluation sur le test",
            "Lit l'ensemble de **test une seule fois** (le dispositif refuse une deuxième lecture) et compare le modèle à la règle de seuils sur des runs jamais vus.",
            "le candidat choisi, le jeu de test", "les métriques du modèle et de la règle (resultat-test.json)",
            commande="dev.py ml-pipeline evaluer (réentraîne et recalcule : mêmes métriques)", demo="ent-evaluer", etat="ok", sous=f"F1 macro {_pct(modele.get('f1_macro'))}",
            details=[("F1 macro du modèle", _pct(modele.get("f1_macro"))), ("Rappel de CONGESTED", _pct(modele.get("rappel_congested"))),
                     ("Fausses alertes / tronçon / jour", _pct(modele.get("fausses_alertes_par_troncon_et_jour"))),
                     ("F1 macro de la règle", _pct((test.get("regle") or {}).get("f1_macro"))), ("Lu le", str(test.get("lu_le", "?")))]))
    else:
        noeuds.append(_noeud("evaluation", 2, 1, "Évaluation sur le test", "Lit le test une seule fois.", "le candidat choisi", "resultat-test.json",
                             commande="dev.py ml-train test", demo="ent-evaluer", etat="arret", sous="aucun résultat trouvé"))

    securite = (verdict or {}).get("securite") or []
    echecs_s = [c.get("code") for c in securite if c.get("ok") is False]
    noeuds.append(_noeud(
        "controles", 4, 0, "Contrôles de sécurité",
        "Avant toute décision : **S1** jeu intact, **S2** l'artefact exporté prédit comme le modèle évalué, **S3** format sans exécution de code, **S4** dépendances sans faille connue, **S5** fiche relue par l'autre membre, **T1** code commité, **R1** métriques reproduites.",
        "le modèle évalué", "un verdict par contrôle (var/pipeline/decision.json)", commande="dev.py ml-pipeline evaluer", demo="ent-evaluer",
        etat="arret" if verdict is None else ("touche" if echecs_s else "ok"),
        sous="rejoue le pipeline pour voir" if verdict is None else ("à corriger : " + ", ".join(echecs_s) if echecs_s else "tous réussis"),
        details=[(c.get("code", "?"), ("réussi" if c.get("ok") else "ÉCHEC") + " : " + str(c.get("libelle", ""))) for c in securite] or [("Dernière exécution", "aucune sur ce poste")]))

    conditions = (verdict or test or {}).get("conditions") or []
    manquees = [c.get("condition") for c in conditions if c.get("remplie") is False]
    decision_texte = str((verdict or test or {}).get("decision", "inconnue"))
    noeuds.append(_noeud(
        "porte", 4, 1, "Porte d'acceptation",
        "Fixée **avant** l'entraînement : cinq conditions (A1 à A5) face à la règle de seuils. Une seule manquée et le modèle est **rejeté** : un résultat négatif documenté est un livrable.",
        "les métriques du test", "décision : accepté ou rejeté", commande="dev.py ml-pipeline porte", demo="ent-porte",
        etat="arret" if not conditions else ("alarme" if manquees else "ok"), sous=("modèle " + decision_texte + (" : " + ", ".join(manquees) + " manquées" if manquees else "")) if conditions else "aucune décision trouvée",
        details=[(c.get("condition", "?"), ("remplie" if c.get("remplie") else "MANQUÉE") + f" : {c.get('libelle', '')} (modèle {c.get('modele')}, exigé {c.get('exige')})") for c in conditions]))

    en_service = _lire(pointeur)
    noeuds.append(_noeud(
        "registre", 5, 0, "Registre des modèles",
        "Chaque exécution est une fiche `model_runs` (jeu, graine, révision Git, métriques). Un modèle **rejeté** est tracé mais **sans fichier de modèle** : il n'entre jamais au registre des modèles en service.",
        "la décision de la porte", "un run « rejected » ou « accepted », et le pointeur du modèle en service",
        commande="dev.py ml-registre en-service (la pile doit tourner)", demo="ent-registre",
        etat="ok" if en_service else "touche", sous="un modèle en service" if en_service else "aucun modèle en service",
        details=[("Modèle en service", str(en_service.get("run_id")) if en_service else "aucun : la règle reste le classificateur"), ("Traçabilité", "jeu, graine, révision Git, métriques")]))

    noeuds.append(_noeud(
        "service", 5, 1, "Traitement en flux",
        "Classe chaque tronçon avec la **règle de seuils** (`classifier.py`). Le branchement d'un modèle appris sur ce service **n'est pas fait** : c'est le lien en pointillé.",
        "les mesures reçues en direct", "l'état Fluide, Ralenti ou Congestionné de chaque tronçon",
        commande="services/traitement/app/flux/classifier.py", etat="touche" if not en_service else "ok", sous="règle de seuils, pas de modèle appris" if not en_service else "modèle en service",
        details=[("Classificateur", "règle de seuils avec hystérésis (ADR-028)"), ("Modèle appris", "non branché")]))

    liens = [
        ("simulateur", "jeu", False), ("jeu", "preparation", False), ("jeu", "reference", False), ("preparation", "entrainement", False),
        ("entrainement", "evaluation", False), ("reference", "evaluation", False), ("entrainement", "controles", False),
        ("evaluation", "porte", False), ("controles", "porte", False), ("porte", "registre", False), ("registre", "service", True),
    ]
    return {"noeuds": noeuds, "liens": [{"de": a, "vers": b, "pointille": p} for a, b, p in liens], "colonnes": COLONNES}
