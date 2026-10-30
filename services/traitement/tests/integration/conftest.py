"""Bases jetables pour les tests d'intégration PostgreSQL (BE-02, BE-03)."""

import pytest

from tests.integration.postgres import temporary_database, upgrade


@pytest.fixture
def empty_database():
    """Une base vide, sans schéma `app`."""
    with temporary_database() as engine:
        yield engine


@pytest.fixture
def migrated_database():
    """Une base vide sur laquelle `alembic upgrade head` a été appliqué."""
    with temporary_database() as engine:
        upgrade(engine)
        yield engine
