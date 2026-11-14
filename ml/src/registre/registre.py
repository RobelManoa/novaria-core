"""Le registre : enregistrer un entraînement, promouvoir ou rejeter un modèle, dire lequel est en service.

Cycle de vie : `enregistrer_entrainement` écrit `trained` ; `rejeter` écrit `rejected` (la trace reste, aucun fichier) ;
`promouvoir` stocke le modèle et son manifeste (écriture unique) puis écrit `registered`. Le **pointeur** `en-service.json`
du magasin dit quel modèle sert : le service d'inférence lit le magasin, jamais MongoDB (il n'a aucun droit sur
`model_runs`, `dev.py db-check`).

Garde minimale de ce module : seul un run dont `metrics.decision` vaut « accepté » se promeut, et seul un fichier du format
sans exécution de code s'enregistre. Le pipeline complet qui calcule la décision (conditions A1 à A5 et S1 à S5 du cadrage)
est l'affaire d'IA-05.
"""

import json
import logging
from datetime import UTC, datetime

from registre import documents
from registre.format_lineaire import NOM as FORMAT, FormatInvalide, ModeleLineaire
from registre.runs import RunStore
from stockage import ObjectStore, ObjetDejaEcrit, sha256

journal = logging.getLogger("registre")
POINTEUR = "en-service.json"
BACKEND = "local"


class RegistreErreur(RuntimeError):
    pass


def cle_du_modele(run_id: str) -> str:
    return f"{documents.valider_run_id(run_id)}/modele.json"


def cle_du_manifeste(run_id: str) -> str:
    return f"{documents.valider_run_id(run_id)}/manifeste.json"


def octets_json(valeur: dict) -> bytes:
    return (json.dumps(valeur, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


class Registre:
    def __init__(self, runs: RunStore, objets: ObjectStore, horloge=lambda: datetime.now(UTC)) -> None:
        self.runs, self.objets, self.horloge = runs, objets, horloge

    def enregistrer_entrainement(self, run_id: str, *, git_sha: str, git_dirty: bool, dataset_id: str, dataset_sha256: str,
                                 seed: int, params: dict, metrics: dict, created_at: datetime | None = None) -> dict:
        """Écrit le document `trained` : paramètres, métriques, jeu (empreinte), révision Git, graine."""
        document = {
            "run_id": run_id, "created_at": created_at or self.horloge(), "git_sha": git_sha, "git_dirty": git_dirty,
            "dataset_id": dataset_id, "dataset_sha256": dataset_sha256, "seed": seed, "params": params, "metrics": metrics,
            "status": documents.TRAINED,
        }
        self.runs.inserer(documents.valider(document))
        return document

    def rejeter(self, run_id: str, raison: str) -> dict:
        """`trained` -> `rejected` : un modèle sous le seuil n'entre pas au registre ; aucun fichier n'est écrit."""
        if not raison.strip():
            raise RegistreErreur("un rejet s'écrit avec sa raison")
        if not self.runs.mettre_a_jour(run_id, {"status": documents.REJECTED, "reason": raison}, statut_attendu=documents.TRAINED):
            raise RegistreErreur(f"{run_id} n'est pas un entraînement en attente (inconnu, déjà rejeté ou déjà enregistré)")
        return self.runs.obtenir(run_id)

    def promouvoir(self, run_id: str, octets_du_modele: bytes) -> dict:
        """`trained` -> `registered` : stocke le modèle et son manifeste, écrit le document, met le pointeur à jour."""
        run = self._obtenir(run_id)
        if run["status"] != documents.TRAINED:
            raise RegistreErreur(f"{run_id} est {run['status']} : seul un entraînement en attente se promeut")
        if run["metrics"].get("decision") != "accepté":
            raise RegistreErreur(f"{run_id} : décision {run['metrics'].get('decision')!r}, « accepté » exigé : un modèle sous le seuil n'entre pas au registre")
        try:
            ModeleLineaire.depuis_octets(octets_du_modele)
        except FormatInvalide as erreur:
            raise RegistreErreur(f"{run_id} : fichier de modèle refusé ({erreur})") from erreur
        empreinte, enregistre_a = sha256(octets_du_modele), self.horloge()
        manifeste = {
            "run_id": run_id, "git_sha": run["git_sha"], "git_dirty": run.get("git_dirty"), "dataset_id": run.get("dataset_id"),
            "dataset_sha256": run["dataset_sha256"], "seed": run["seed"], "model_sha256": empreinte, "model_format": FORMAT,
            "created_at": run["created_at"].isoformat(), "registered_at": enregistre_a.isoformat(),
        }
        self._ecrire_une_fois(cle_du_modele(run_id), octets_du_modele)
        self._ecrire_une_fois(cle_du_manifeste(run_id), octets_json(manifeste))
        champs = {"status": documents.REGISTERED, "model_sha256": empreinte, "model_uri": f"{BACKEND}:{cle_du_modele(run_id)}",
                  "model_format": FORMAT, "registered_at": enregistre_a}
        if not self.runs.mettre_a_jour(run_id, champs, statut_attendu=documents.TRAINED):
            raise RegistreErreur(f"{run_id} a changé d'état pendant la promotion : rien n'est mis en service")
        self._pointer(run_id, octets_json(manifeste))
        journal.info("modèle enregistré et en service", extra={"run_id": run_id, "model_sha256": empreinte})
        return self.runs.obtenir(run_id)

    def remettre_en_service(self, run_id: str) -> dict:
        """Retour à une version précédente : le modèle enregistré redevient le plus récent (ADR-017, section 4.3)."""
        run = self._obtenir(run_id)
        if run["status"] != documents.REGISTERED:
            raise RegistreErreur(f"{run_id} n'est pas enregistré : on ne remet en service qu'un modèle enregistré")
        octets = self.objets.get(cle_du_modele(run_id))
        if sha256(octets) != run["model_sha256"]:
            journal.warning("modèle altéré : remise en service refusée", extra={"run_id": run_id})
            raise RegistreErreur(f"{run_id} : le fichier du modèle n'a plus l'empreinte enregistrée")
        manifeste = self.objets.get(cle_du_manifeste(run_id))
        if not self.runs.mettre_a_jour(run_id, {"registered_at": self.horloge()}, statut_attendu=documents.REGISTERED):
            raise RegistreErreur(f"{run_id} a changé d'état : rien n'est remis en service")
        self._pointer(run_id, manifeste)
        return self.runs.obtenir(run_id)

    def en_service(self) -> dict | None:
        """Le document du modèle en service : le plus récemment enregistré ou remis en service."""
        return self.runs.dernier_en_service()

    def _obtenir(self, run_id: str) -> dict:
        run = self.runs.obtenir(documents.valider_run_id(run_id))
        if run is None:
            raise RegistreErreur(f"{run_id} : aucun entraînement enregistré sous ce nom")
        return run

    def _ecrire_une_fois(self, cle: str, octets: bytes) -> None:
        """Écriture unique ; une reprise après échec retrouve des octets identiques et passe, des octets différents échouent."""
        try:
            self.objets.put(cle, octets)
        except ObjetDejaEcrit as erreur:
            if sha256(self.objets.get(cle)) != sha256(octets):
                raise RegistreErreur(f"{cle} existe avec un autre contenu : un objet versionné ne se réécrit pas") from erreur

    def _pointer(self, run_id: str, octets_du_manifeste: bytes) -> None:
        self.objets.put(POINTEUR, octets_json({"run_id": run_id, "manifeste_sha256": sha256(octets_du_manifeste)}), remplacer=True)
