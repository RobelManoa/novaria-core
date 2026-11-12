"""Le document `model_runs` (dictionnaire de données, section 10.6) : sa forme, sa validation, ses états.

Une exécution d'entraînement passe par `trained`, puis `registered` (elle entre au registre) ou `rejected` (elle n'y
entre pas : la trace reste, aucun fichier de modèle n'est écrit). Les champs obligatoires sont ceux du validateur MongoDB ;
les champs `dataset_id`, `git_dirty`, `model_uri`, `model_format`, `registered_at` et `reason` sont facultatifs.
"""

import re
from datetime import datetime

TRAINED, REJECTED, REGISTERED = "trained", "rejected", "registered"
ETATS = (TRAINED, REJECTED, REGISTERED)
RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}")  # aussi un segment de clé du magasin : jamais de chemin
SHA256 = re.compile(r"[0-9a-f]{64}")
GIT_SHA = re.compile(r"[0-9a-f]{40}")
OBLIGATOIRES = ("run_id", "created_at", "git_sha", "dataset_sha256", "seed", "params", "metrics", "status")
FACULTATIFS = ("git_dirty", "dataset_id", "model_sha256", "model_uri", "model_format", "registered_at", "reason")


class DocumentInvalide(ValueError):
    pass


def valider_run_id(run_id) -> str:
    """Un identifiant de run sûr : c'est aussi un segment de clé du magasin, donc jamais de chemin."""
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise DocumentInvalide(f"run_id invalide : {run_id!r} (minuscules, chiffres, . _ - ; 100 caractères au plus)")
    return run_id


def valider(document: dict) -> dict:
    """Refuse un document mal formé avant de l'écrire ; rend le document."""
    ecarts = []
    inconnus = sorted(set(document) - set(OBLIGATOIRES) - set(FACULTATIFS))
    if inconnus:
        ecarts.append(f"champs inconnus : {inconnus}")
    ecarts += [f"{nom} est obligatoire" for nom in OBLIGATOIRES if nom not in document]
    if not ecarts:
        controles = (
            (isinstance(document["run_id"], str) and RUN_ID.fullmatch(document["run_id"]), "run_id : minuscules, chiffres, . _ - (100 au plus)"),
            (isinstance(document["created_at"], datetime) and document["created_at"].tzinfo is not None, "created_at : date avec fuseau"),
            (isinstance(document["git_sha"], str) and GIT_SHA.fullmatch(document["git_sha"]), "git_sha : 40 caractères hexadécimaux minuscules"),
            (isinstance(document["dataset_sha256"], str) and SHA256.fullmatch(document["dataset_sha256"]), "dataset_sha256 : 64 caractères hexadécimaux minuscules"),
            (isinstance(document["seed"], int) and not isinstance(document["seed"], bool), "seed : entier"),
            (isinstance(document["params"], dict), "params : objet"),
            (isinstance(document["metrics"], dict), "metrics : objet"),
            (document["status"] in ETATS, f"status : {ETATS}"),
            ("model_sha256" not in document or (isinstance(document["model_sha256"], str) and SHA256.fullmatch(document["model_sha256"])), "model_sha256 : 64 caractères hexadécimaux minuscules"),
            ("git_dirty" not in document or isinstance(document["git_dirty"], bool), "git_dirty : booléen"),
            ("registered_at" not in document or (isinstance(document["registered_at"], datetime) and document["registered_at"].tzinfo is not None), "registered_at : date avec fuseau"),
        )
        ecarts += [message for ok, message in controles if not ok]
        if document["status"] == REGISTERED:
            ecarts += [f"un modèle enregistré a son champ {nom}" for nom in ("model_sha256", "model_uri", "model_format", "registered_at") if nom not in document]
        if document["status"] != REGISTERED and "model_sha256" in document:
            ecarts.append("seul un modèle enregistré a un fichier de modèle")
    if ecarts:
        raise DocumentInvalide("; ".join(ecarts))
    return document


def en_json(document: dict) -> dict:
    """Le document sans dates Python (ISO 8601), pour l'affichage et les exports."""
    return {nom: (valeur.isoformat() if isinstance(valeur, datetime) else valeur) for nom, valeur in document.items() if nom != "_id"}
