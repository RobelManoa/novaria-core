"""Copie brute et archive des rejets dans MongoDB (ADR-024) : compte `svc_collecte`.

Droits du compte : `find` et `insert` sur `raw_events` et `rejects`, rien d'autre. Le service ne
peut donc ni modifier ni supprimer un document : c'est ce qui impose l'ordre « publier puis stocker
» (voir `app/services/ingestion.py`). L'idempotence repose sur l'index unique `uniq_event_id` de
`raw_events` : une seconde écriture du même `id` est refusée par la base, même si deux instances du
service reçoivent le même message en même temps.
"""

import json
import logging
import threading
from collections.abc import Callable

from bson.errors import InvalidDocument
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError, WriteError

from app.services.ingestion import StoreFailed

logger = logging.getLogger("app.mongo")


class MongoCollections:
    """Une connexion partagée, ouverte à la première utilisation (démarrage sans MongoDB)."""

    def __init__(
        self,
        url: str,
        database: str,
        *,
        timeout_ms: int = 3000,
        client_factory: Callable[..., MongoClient] = MongoClient,
    ) -> None:
        self._url = url
        self._database = database
        self._timeout_ms = timeout_ms
        self._factory = client_factory
        self._client: MongoClient | None = None
        self._lock = threading.Lock()

    def collection(self, name: str) -> Collection:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    # La connexion est paresseuse : aucune panne ici, seulement à la première
                    # opération.
                    self._client = self._factory(
                        self._url,
                        serverSelectionTimeoutMS=self._timeout_ms,
                        connectTimeoutMS=self._timeout_ms,
                        appname="novaria-collecte",
                        maxPoolSize=100,
                    )
        return self._client[self._database][name]

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()


class MongoRawEvents:
    def __init__(self, collections: MongoCollections) -> None:
        self._collections = collections

    def exists(self, event_id: str) -> bool:
        try:
            return (
                self._collections.collection("raw_events").find_one({"id": event_id}, {"_id": 1})
                is not None
            )
        except PyMongoError as error:
            logger.error(
                "lecture de raw_events échouée", extra={"fields": {"error": type(error).__name__}}
            )
            raise StoreFailed(type(error).__name__) from error

    def insert(self, document: dict) -> bool:
        try:
            self._collections.collection("raw_events").insert_one(document)
        except DuplicateKeyError:
            return False
        except PyMongoError as error:
            logger.error(
                "écriture dans raw_events échouée",
                extra={"fields": {"error": type(error).__name__}},
            )
            raise StoreFailed(type(error).__name__) from error
        return True


class MongoRejects:
    def __init__(self, collections: MongoCollections) -> None:
        self._collections = collections

    def insert(self, document: dict) -> None:
        collection = self._collections.collection("rejects")
        try:
            try:
                collection.insert_one(dict(document))
            except (InvalidDocument, WriteError):
                # Une charge que BSON refuse (clé avec un octet nul, imbrication trop profonde...)
                # est gardée sous forme de texte JSON : le rejet est archivé, pas perdu.
                collection.insert_one(
                    {**document, "original_payload": _as_text(document["original_payload"])}
                )
        except PyMongoError as error:
            logger.error(
                "écriture dans rejects échouée", extra={"fields": {"error": type(error).__name__}}
            )
            raise StoreFailed(type(error).__name__) from error


def _as_text(payload: object) -> str:
    return (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, ensure_ascii=False, default=str)
    )
