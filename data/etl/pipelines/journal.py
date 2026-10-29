"""Journal des ingestions dans MongoDB (collection `ingestion_runs`, dictionnaire de données section 10.7).

Un document par fichier brut reçu, reconnu par sa clé `load_key` = jeu + fenêtre + SHA-256. Rejouer une ingestion dont
le fichier est identique ne crée aucun document : il incrémente `executions` et met à jour `last_seen_at`.
pymongo n'est importé qu'à l'écriture : les tests sans base n'ont pas besoin de l'installer.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple, Protocol

COLLECTION = "ingestion_runs"
MESSAGE_DROITS = (
    "MongoDB refuse l'écriture dans ingestion_runs : collection ou droits absents. Une base créée avant DAT-03 ne les "
    "a pas : recréer la base locale (python scripts/dev/dev.py db-reset), voir docs/03-donnees/base-de-donnees-locale.md."
)
CODE_NON_AUTORISE = 13
CODE_VALIDATION = 121


class ErreurJournal(Exception):
    """Le journal n'a pas pu être écrit (base injoignable, droits, validateur)."""


class Passage(NamedTuple):
    nouveau: bool  # vrai si ce fichier n'était pas encore journalisé
    executions: int  # nombre de fois où ce même fichier a été reçu, cette exécution comprise


class Journal(Protocol):
    def enregistrer(self, entree: dict, *, maintenant: datetime, run_id: str) -> Passage: ...


class JournalMongo:
    def __init__(self, collection) -> None:
        self._collection = collection

    @classmethod
    def depuis_url(cls, url: str) -> JournalMongo:
        """Ouvre la base nommée dans l'adresse (…/novaria?authSource=novaria) avec le compte qu'elle contient."""
        from pymongo import MongoClient

        try:
            base = MongoClient(url, serverSelectionTimeoutMS=5000).get_default_database()
        except Exception as erreur:  # adresse sans nom de base, ou mal formée
            raise ErreurJournal(f"Adresse MongoDB inutilisable : {type(erreur).__name__}.") from erreur
        return cls(base[COLLECTION])

    def enregistrer(self, entree: dict, *, maintenant: datetime, run_id: str) -> Passage:
        from pymongo.errors import DuplicateKeyError

        document = {cle: valeur for cle, valeur in entree.items() if cle != "load_key"}
        mise_a_jour = {
            "$setOnInsert": {**document, "run_id": run_id, "ingested_at": maintenant},
            "$set": {"last_seen_at": maintenant, "last_run_id": run_id},
            "$inc": {"executions": 1},
        }
        for essai in (1, 2):
            try:
                resultat = self._ecrire(entree["load_key"], mise_a_jour)
                break
            except DuplicateKeyError:
                # Deux exécutions simultanées sur le même fichier : la seconde retrouve le document de la première.
                if essai == 2:
                    raise ErreurJournal("Clé load_key déjà prise par une autre exécution : relancer.") from None
        executions = int(resultat["executions"])
        return Passage(nouveau=executions == 1, executions=executions)

    def _ecrire(self, cle: str, mise_a_jour: dict) -> dict:
        """Une écriture atomique (créer ou incrémenter). Les erreurs du pilote deviennent des ErreurJournal explicites ;
        seule la collision de clé (DuplicateKeyError) est relayée, pour que l'appelant retente."""
        from pymongo import ReturnDocument
        from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError

        try:
            return self._collection.find_one_and_update({"load_key": cle}, mise_a_jour, upsert=True, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            raise
        except OperationFailure as erreur:
            raise ErreurJournal(message_operation(erreur)) from erreur
        except PyMongoError as erreur:
            raise ErreurJournal(f"MongoDB injoignable ({type(erreur).__name__}) : lancer db-up.") from erreur


def message_operation(erreur) -> str:
    if erreur.code == CODE_NON_AUTORISE:
        return MESSAGE_DROITS
    if erreur.code == CODE_VALIDATION:
        return "Le validateur de ingestion_runs refuse l'entrée : " + str(erreur)
    return f"MongoDB a refusé l'écriture (code {erreur.code})."
