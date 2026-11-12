"""Côté service : charger le modèle en service depuis le magasin, avec son manifeste, sans MongoDB et sans scikit-learn.

Le service lit `en-service.json`, puis le manifeste et le modèle du run désigné. **Rien n'est chargé** si l'empreinte du
manifeste n'est pas celle du pointeur, si l'empreinte du modèle n'est pas celle du manifeste, ou si le fichier n'est pas
exactement au format `novaria-modele-lineaire` : une ligne de journal dit pourquoi (cadrage ML, S2 et S3).
"""

import json
import logging
from dataclasses import dataclass

from registre import documents
from registre.format_lineaire import NOM as FORMAT, FormatInvalide, ModeleLineaire
from registre.registre import POINTEUR, cle_du_manifeste, cle_du_modele
from registre.stockage import ObjectStore, StockageErreur, sha256

journal = logging.getLogger("registre")


class ModeleRefuse(RuntimeError):
    """Le modèle désigné ne passe pas les contrôles : le service garde la règle de seuils."""


@dataclass(frozen=True)
class ModeleEnService:
    run_id: str
    manifeste: dict  # run_id, git_sha, dataset_id, dataset_sha256, seed, model_sha256... : la lignée du modèle
    modele: ModeleLineaire

    def predire(self, lignes: list[dict]) -> list[str]:
        return self.modele.predire(lignes)


def _json(octets: bytes, nom: str) -> dict:
    try:
        valeur = json.loads(octets.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as erreur:
        raise ModeleRefuse(f"{nom} illisible") from erreur
    if not isinstance(valeur, dict):
        raise ModeleRefuse(f"{nom} : objet JSON attendu")
    return valeur


def charger_le_modele_en_service(objets: ObjectStore) -> ModeleEnService:
    try:
        return _charger(objets)
    except (ModeleRefuse, StockageErreur, FormatInvalide, documents.DocumentInvalide) as erreur:
        journal.warning("modèle en service refusé", extra={"raison": str(erreur)})
        raise ModeleRefuse(str(erreur)) from erreur


def _charger(objets: ObjectStore) -> ModeleEnService:
    pointeur = _json(objets.get(POINTEUR), POINTEUR)
    run_id = documents.valider_run_id(pointeur.get("run_id"))
    octets_du_manifeste = objets.get(cle_du_manifeste(run_id))
    if sha256(octets_du_manifeste) != pointeur.get("manifeste_sha256"):
        raise ModeleRefuse(f"manifeste de {run_id} : empreinte différente de celle du pointeur")
    manifeste = _json(octets_du_manifeste, "manifeste")
    if manifeste.get("run_id") != run_id or manifeste.get("model_format") != FORMAT:
        raise ModeleRefuse(f"manifeste de {run_id} : run ou format inattendu")
    octets = objets.get(cle_du_modele(run_id))
    if sha256(octets) != manifeste.get("model_sha256"):
        raise ModeleRefuse(f"modèle de {run_id} : empreinte différente de celle du manifeste (fichier altéré)")
    return ModeleEnService(run_id, manifeste, ModeleLineaire.depuis_octets(octets))
