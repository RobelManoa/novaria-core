"""Dépôts MongoDB de l'audit (BE-05), sans base : appels lus, pas exécutés.

Leur exécution réelle est vérifiée par `tests/integration/test_audit_mongo.py`.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pymongo.errors import DuplicateKeyError

from app.repositories import audit as module
from app.repositories.audit import MongoAuditRepository, MongoUsageRepository, open_collections

TRANCHE = datetime(2026, 10, 20, 8, tzinfo=UTC)
DOUBLON = DuplicateKeyError("E11000 duplicate key")


def test_an_entry_is_inserted_as_is():
    collection = MagicMock()
    entree = {"actor": "u"}
    MongoAuditRepository(collection).insert(entree)
    collection.insert_one.assert_called_once_with(entree)


def test_a_counter_is_incremented_by_an_upsert_on_the_endpoint_and_the_hour():
    collection = MagicMock()
    MongoUsageRepository(collection).increment("GET /x", TRANCHE)
    collection.update_one.assert_called_once_with(
        {"endpoint": "GET /x", "bucket_start": TRANCHE}, {"$inc": {"count": 1}}, upsert=True
    )


def test_a_duplicate_on_creation_is_retried_once_on_the_row_that_now_exists():
    collection = MagicMock()
    collection.update_one.side_effect = [DOUBLON, MagicMock()]
    MongoUsageRepository(collection).increment("GET /x", TRANCHE)
    assert collection.update_one.call_count == 2


def test_a_second_duplicate_is_not_hidden():
    collection = MagicMock()
    collection.update_one.side_effect = DOUBLON
    with pytest.raises(DuplicateKeyError):
        MongoUsageRepository(collection).increment("GET /x", TRANCHE)
    assert collection.update_one.call_count == 2


def test_the_collections_are_the_two_of_the_backend_role(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(module, "MongoClient", MagicMock(return_value=client))
    base = client.get_default_database.return_value
    audit, usage = open_collections("mongodb://u:p@h/novaria?authSource=novaria")
    module.MongoClient.assert_called_once_with(
        "mongodb://u:p@h/novaria?authSource=novaria", serverSelectionTimeoutMS=2000
    )
    assert audit._collection is base["audit_logs"]
    assert usage._collection is base["usage_stats"]
