"""Outils des tests contre un vrai MongoDB (BE-05) : le compte `svc_backend` du projet.

Ignoré sans `NOVARIA_TEST_MONGO_URL` : adresse du compte `svc_backend` d'un MongoDB local, par
exemple `mongodb://svc_backend:…@127.0.0.1:27017/novaria?authSource=novaria`. Ce compte n'a que les
droits de production (lire et insérer dans `audit_logs`, lire/insérer/modifier `usage_stats`) : les
tests vérifient donc aussi qu'ils suffisent. Il ne peut rien supprimer ; chaque test écrit sous un
identifiant unique, et `NOVARIA_TEST_MONGO_ADMIN_URL` (compte administrateur, facultatif) sert à
effacer ces traces après coup.
"""

import os
import uuid

import pytest
from pymongo import MongoClient

URL = os.environ.get("NOVARIA_TEST_MONGO_URL")
ADMIN_URL = os.environ.get("NOVARIA_TEST_MONGO_ADMIN_URL")
needs_mongo = pytest.mark.skipif(
    not URL, reason="NOVARIA_TEST_MONGO_URL absent : MongoDB local requis"
)


def database(url: str):
    return MongoClient(url, serverSelectionTimeoutMS=3000).get_default_database()


def unique_marker() -> str:
    """Identifiant propre à un test : permet de retrouver (et d'effacer) ce qu'il a écrit."""
    return f"essai-{uuid.uuid4()}"


def erase(actors: list[str], endpoints: list[str]) -> None:
    if not ADMIN_URL:
        return
    base = database(ADMIN_URL)
    base.audit_logs.delete_many({"actor": {"$in": actors}})
    base.usage_stats.delete_many({"endpoint": {"$in": endpoints}})
