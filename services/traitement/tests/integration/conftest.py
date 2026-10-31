"""Bases jetables pour les tests d'intégration PostgreSQL (BE-02, BE-03)."""

import pytest

from tests.integration.postgres import apply_sql_migrations, temporary_database, upgrade


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


@pytest.fixture
def warehouse():
    """Une base vide avec `dwh` et `alertes`, migrations SQL appliquées (réseau fictif compris)."""
    with temporary_database() as engine:
        apply_sql_migrations(engine)
        yield engine
