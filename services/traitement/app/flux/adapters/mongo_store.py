"""MongoDB, compte `svc_traitement` : archive des rejets et statistiques de traitement.

Droits (db/mongo/init) : `rejects` lire et insérer ; `processing_stats` lire, insérer et modifier.

- `rejects` : l'`_id` est celui du message d'erreur (partition et offset d'origine) ; un rejeu qui
  réinsère le même rejet est ignoré (clé dupliquée), l'archive ne grossit pas.
- `processing_stats` : un document par (`kind`, début de minute, tronçon) ; les compteurs sont
  incrémentés (`$inc`). Un rejeu après panne peut compter deux fois : les compteurs sont
  « au moins une fois », comme la livraison (docs/03-donnees/flux.md).
"""

import json
import logging
from datetime import datetime

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, InvalidDocument, PyMongoError, WriteError

from app.flux.ports import StoreFailed

logger = logging.getLogger("app.flux.mongo")

SERVER_SELECTION_TIMEOUT_MS = 5000


class MongoStore:
    def __init__(self, url: str) -> None:
        self._client = MongoClient(url, serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS)
        self._database = self._client.get_default_database()

    def insert(self, document: dict) -> None:
        """`RejectArchive` : copie du rejet ; ignorée si elle existe déjà."""
        collection = self._database["rejects"]
        try:
            try:
                collection.insert_one(dict(document))
            except (InvalidDocument, WriteError):
                # Une charge que BSON refuse (clé avec un octet nul, imbrication trop profonde...)
                # est gardée sous forme de texte JSON : le rejet est archivé, pas perdu.
                payload = document["original_payload"]
                text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
                collection.insert_one({**document, "original_payload": text})
        except DuplicateKeyError:
            return
        except PyMongoError as error:
            logger.error(
                "écriture dans rejects échouée", extra={"fields": {"error": type(error).__name__}}
            )
            raise StoreFailed(type(error).__name__) from error

    def add(
        self, kind: str, window_start: datetime, road_segment_id: str | None, counts: dict[str, int]
    ) -> None:
        """`StatsStore` : incrémente les compteurs du document (`kind`, minute, tronçon)."""
        selector: dict = {"kind": kind, "window_start": window_start}
        selector["road_segment_id"] = road_segment_id if road_segment_id else {"$exists": False}
        increments = {f"values.{name}": int(value) for name, value in counts.items()}
        try:
            self._database["processing_stats"].update_one(
                selector, {"$inc": increments}, upsert=True
            )
        except PyMongoError as error:
            logger.error(
                "statistiques non écrites", extra={"fields": {"error": type(error).__name__}}
            )
            raise StoreFailed(type(error).__name__) from error

    def close(self) -> None:
        self._client.close()
