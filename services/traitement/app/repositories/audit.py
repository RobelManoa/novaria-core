"""Écriture dans MongoDB : `audit_logs` et `usage_stats` (BE-05), avec le compte `svc_backend`.

Droits de ce compte (db/mongo/init) : `audit_logs` lire et insérer ; `usage_stats` lire, insérer et
modifier. Il ne peut ni supprimer ni modifier une entrée d'audit : le journal ne se réécrit pas.
"""

from datetime import datetime

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

AUDIT_COLLECTION = "audit_logs"
USAGE_COLLECTION = "usage_stats"
# Une base éteinte coûte 2 s au plus, une fois ; ensuite le journal fait une pause.
SERVER_SELECTION_TIMEOUT_MS = 2000


class MongoAuditRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def insert(self, entry: dict) -> None:
        self._collection.insert_one(entry)


class MongoUsageRepository:
    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    def increment(self, endpoint: str, bucket: datetime) -> None:
        """Ajoute 1 au compteur de (point d'accès, tranche) ; le crée au premier appel.

        L'index unique `uniq_endpoint_bucket` refuse un doublon : si deux appels créent la ligne
        en même temps, le second échoue sur l'index et recommence, cette fois sur la ligne
        existante.
        """
        filtre = {"endpoint": endpoint, "bucket_start": bucket}
        for essai in (1, 2):
            try:
                self._collection.update_one(filtre, {"$inc": {"count": 1}}, upsert=True)
                return
            except DuplicateKeyError:
                if essai == 2:
                    raise


def open_collections(url: str) -> tuple[MongoAuditRepository, MongoUsageRepository]:
    """Ouvre la base nommée dans l'adresse (`…/novaria?authSource=novaria`)."""
    client = MongoClient(url, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS)
    base = client.get_default_database()
    return MongoAuditRepository(base[AUDIT_COLLECTION]), MongoUsageRepository(
        base[USAGE_COLLECTION]
    )
