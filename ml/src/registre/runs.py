"""Port `RunStore` (la collection `model_runs`) et ses deux adaptateurs : mémoire (essais) et MongoDB (compte `svc_ml`).

Les écritures sont des **comparaisons avec échange** : `mettre_a_jour` ne change un document que s'il est encore dans
l'état attendu. Deux promotions simultanées ne s'écrasent pas ; un document enregistré ne change que par ces champs.
"""

import copy
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Protocol

from registre.documents import REGISTERED, valider, valider_run_id


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


class FichierRunStore:
    """`model_runs` dans un dossier : un fichier JSON par run (`<run_id>.json`). Pour une exécution sans MongoDB (la CI).

    Chaque écriture est atomique (fichier temporaire puis échange) et le comportement est celui des autres magasins :
    unicité du `run_id`, mise à jour conditionnelle. Il sert des étapes successives d'un même flux de travail, pas
    des écritures simultanées de plusieurs processus.
    """

    DATES = ("created_at", "registered_at")

    def __init__(self, racine: Path) -> None:
        self.racine = Path(racine)

    def _chemin(self, run_id: str) -> Path:
        racine = self.racine.resolve()
        chemin = (racine / f"{valider_run_id(run_id)}.json").resolve()
        if not chemin.is_relative_to(racine):
            raise RunDejaEnregistre(f"chemin hors du dossier des runs : {run_id!r}")
        return chemin

    def _ecrire(self, chemin: Path, document: dict, *, exclusif: bool) -> None:
        sortie = {nom: (valeur.isoformat() if isinstance(valeur, datetime) else valeur) for nom, valeur in document.items()}
        octets = (json.dumps(sortie, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        descripteur, temporaire = tempfile.mkstemp(dir=chemin.parent, prefix=".ecriture-")
        try:
            with os.fdopen(descripteur, "wb") as fichier:
                fichier.write(octets)
            if exclusif:
                os.link(temporaire, chemin)  # échoue si le run existe déjà
            else:
                os.replace(temporaire, chemin)
        except FileExistsError as erreur:
            raise RunDejaEnregistre(chemin.stem) from erreur
        finally:
            if os.path.exists(temporaire):
                os.unlink(temporaire)

    def _lire(self, chemin: Path) -> dict | None:
        if not chemin.is_file():
            return None
        document = json.loads(chemin.read_text(encoding="utf-8"))
        for nom in self.DATES:
            if nom in document:
                document[nom] = datetime.fromisoformat(document[nom])
        return document

    def inserer(self, document: dict) -> None:
        valider(document)
        self._ecrire(self._chemin(document["run_id"]), document, exclusif=True)

    def obtenir(self, run_id: str) -> dict | None:
        return self._lire(self._chemin(run_id))

    def lister(self, status: str | None = None) -> list[dict]:
        documents = [self._lire(chemin) for chemin in sorted(self.racine.glob("*.json"))] if self.racine.is_dir() else []
        return sorted((d for d in documents if d is not None and status in (None, d["status"])), key=lambda d: d["created_at"])

    def mettre_a_jour(self, run_id: str, champs: dict, *, statut_attendu: str) -> bool:
        chemin = self._chemin(run_id)
        courant = self._lire(chemin)
        if courant is None or courant["status"] != statut_attendu:
            return False
        suite = {**courant, **champs}
        valider(suite)
        self._ecrire(chemin, suite, exclusif=False)
        return True

    def dernier_en_service(self) -> dict | None:
        enregistres = self.lister(REGISTERED)
        return max(enregistres, key=lambda d: (d["registered_at"], d["created_at"])) if enregistres else None
