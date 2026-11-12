"""Port `RunStore` (la collection `model_runs`) et ses deux adaptateurs : mémoire (essais) et MongoDB (compte `svc_ml`).

Les écritures sont des **comparaisons avec échange** : `mettre_a_jour` ne change un document que s'il est encore dans
l'état attendu. Deux promotions simultanées ne s'écrasent pas ; un document enregistré ne change que par ces champs.
"""

import copy
from typing import Protocol

from registre.documents import REGISTERED, valider


class RunDejaEnregistre(RuntimeError):
    pass


class RunStore(Protocol):
    def inserer(self, document: dict) -> None: ...
    def obtenir(self, run_id: str) -> dict | None: ...
    def lister(self, status: str | None = None) -> list[dict]: ...
    def mettre_a_jour(self, run_id: str, champs: dict, *, statut_attendu: str) -> bool: ...
    def dernier_en_service(self) -> dict | None: ...


class MemoireRunStore:
    """Une collection en mémoire : pour les essais, avec le même comportement que MongoDB (unicité, échange conditionnel)."""

    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}

    def inserer(self, document: dict) -> None:
        valider(document)
        if document["run_id"] in self.documents:
            raise RunDejaEnregistre(document["run_id"])
        self.documents[document["run_id"]] = copy.deepcopy(document)

    def obtenir(self, run_id: str) -> dict | None:
        return copy.deepcopy(self.documents.get(run_id))

    def lister(self, status: str | None = None) -> list[dict]:
        return [copy.deepcopy(d) for d in sorted(self.documents.values(), key=lambda d: d["created_at"]) if status in (None, d["status"])]

    def mettre_a_jour(self, run_id: str, champs: dict, *, statut_attendu: str) -> bool:
        courant = self.documents.get(run_id)
        if courant is None or courant["status"] != statut_attendu:
            return False
        suite = {**courant, **champs}
        valider(suite)
        self.documents[run_id] = suite
        return True

    def dernier_en_service(self) -> dict | None:
        enregistres = [d for d in self.documents.values() if d["status"] == REGISTERED]
        return copy.deepcopy(max(enregistres, key=lambda d: (d["registered_at"], d["created_at"]))) if enregistres else None


class MongoRunStore:
    """`model_runs` dans MongoDB. L'adresse (avec le compte `svc_ml`) vient de l'environnement, jamais d'un fichier."""

    def __init__(self, collection) -> None:
        self.collection = collection

    @classmethod
    def depuis_l_adresse(cls, adresse: str, delai_ms: int = 3000) -> "MongoRunStore":
        from pymongo import MongoClient

        base = MongoClient(adresse, serverSelectionTimeoutMS=delai_ms, tz_aware=True).get_default_database()
        return cls(base["model_runs"])

    def fermer(self) -> None:
        """Libère la connexion (sans effet sur une collection qui n'en a pas)."""
        client = getattr(getattr(self.collection, "database", None), "client", None)
        if client is not None:
            client.close()

    def inserer(self, document: dict) -> None:
        from pymongo.errors import DuplicateKeyError

        valider(document)
        try:
            self.collection.insert_one(copy.deepcopy(document))
        except DuplicateKeyError as erreur:
            raise RunDejaEnregistre(document["run_id"]) from erreur

    def obtenir(self, run_id: str) -> dict | None:
        trouve = self.collection.find_one({"run_id": run_id}, {"_id": 0})
        return trouve

    def lister(self, status: str | None = None) -> list[dict]:
        filtre = {} if status is None else {"status": status}
        return list(self.collection.find(filtre, {"_id": 0}).sort("created_at", 1))

    def mettre_a_jour(self, run_id: str, champs: dict, *, statut_attendu: str) -> bool:
        courant = self.obtenir(run_id)
        if courant is None or courant["status"] != statut_attendu:
            return False
        valider({**courant, **champs})
        resultat = self.collection.update_one({"run_id": run_id, "status": statut_attendu}, {"$set": champs})
        return resultat.matched_count == 1

    def dernier_en_service(self) -> dict | None:
        trouves = list(self.collection.find({"status": REGISTERED}, {"_id": 0}).sort([("registered_at", -1), ("created_at", -1)]).limit(1))
        return trouves[0] if trouves else None
