"""Journal d'audit des commandes de feux : la collection `audit_logs` de MongoDB (BE-05, MS-12).

Le compte du service (`svc_reponse`, rôle `role_reponse`) peut **lire et insérer** dans
`audit_logs`, rien d'autre : une entrée ne se modifie ni ne se supprime. Le validateur de la
collection impose `ts`, `service`, `actor`, `action` et `outcome` (ok, denied, error).
"""

import base64
import binascii
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.services.ports import AuditFailed

logger = logging.getLogger("app.audit")

COLLECTION = "audit_logs"
SERVICE = "reponse"
COMMAND_ACTIONS = ["signal.command.SET_PHASE", "signal.command.RESUME_AUTOMATIC"]


class InvalidCursor(ValueError):
    """Le curseur n'est pas un curseur rendu par ce service."""


def encode_cursor(entry: dict[str, Any]) -> str:
    stamp = int(entry["ts"].astimezone(UTC).timestamp() * 1000)
    raw = json.dumps({"ts": stamp, "id": str(entry["_id"])}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, ObjectId]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return datetime.fromtimestamp(int(data["ts"]) / 1000, UTC), ObjectId(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError, InvalidId, OverflowError) as error:
        raise InvalidCursor from error


class MongoAuditLog:
    def __init__(
        self,
        url: str,
        *,
        timeout_ms: int = 2000,
        client_factory: Callable[..., MongoClient] = MongoClient,
    ) -> None:
        # `tz_aware` : les dates reviennent en UTC. Les délais courts : une base éteinte ne retient
        # pas une requête plus de `timeout_ms` (la commande est alors refusée, pas retardée).
        self._client = client_factory(
            url,
            tz_aware=True,
            serverSelectionTimeoutMS=timeout_ms,
            connectTimeoutMS=timeout_ms,
            socketTimeoutMS=timeout_ms,
            appname="novaria-reponse",
        )
        self._logs = self._client.get_default_database()[COLLECTION]

    def record(self, entry: dict[str, Any]) -> None:
        try:
            self._logs.insert_one(dict(entry))
        except PyMongoError as error:
            logger.error(
                "écriture dans audit_logs impossible",
                extra={"fields": {"error": type(error).__name__, "counter": "audit_failures"}},
            )
            raise AuditFailed(type(error).__name__) from error

    def history(
        self, intersection_id: str, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        query: dict[str, Any] = {
            "service": SERVICE,
            "action": {"$in": COMMAND_ACTIONS},
            "details.intersection_id": intersection_id,
        }
        if cursor:
            stamp, last = decode_cursor(cursor)
            query["$or"] = [{"ts": {"$lt": stamp}}, {"ts": stamp, "_id": {"$lt": last}}]
        try:
            found = list(self._logs.find(query).sort([("ts", -1), ("_id", -1)]).limit(limit + 1))
        except PyMongoError as error:
            raise AuditFailed(type(error).__name__) from error
        page = found[:limit]
        return page, encode_cursor(page[-1]) if len(found) > limit else None

    def close(self) -> None:
        self._client.close()
