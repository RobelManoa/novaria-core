"""Outils des tests contre un vrai PostgreSQL : base jetable, migrations Alembic.

Ignoré sans `NOVARIA_TEST_POSTGRES_ADMIN_URL` : adresse SQLAlchemy du compte administrateur d'un
PostgreSQL local, par exemple `postgresql+psycopg://novaria_admin:…@127.0.0.1:5432/novaria`
(docs/03-donnees/base-de-donnees-locale.md). Chaque test crée sa propre base vide et la supprime
ensuite : la base du projet n'est pas touchée.
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

SERVICE = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get("NOVARIA_TEST_POSTGRES_ADMIN_URL")
needs_postgres = pytest.mark.skipif(
    not ADMIN_URL, reason="NOVARIA_TEST_POSTGRES_ADMIN_URL absent : PostgreSQL local requis"
)


def alembic_on(connection) -> Config:
    config = Config(str(SERVICE / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.attributes["connection"] = connection
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    with engine.begin() as connection:
        command.upgrade(alembic_on(connection), revision)


def downgrade(engine: Engine, revision: str) -> None:
    with engine.begin() as connection:
        command.downgrade(alembic_on(connection), revision)


@contextmanager
def temporary_database() -> Iterator[Engine]:
    """Une base vide (aucun schéma `app`), créée pour l'usage puis supprimée."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    name = f"novaria_test_{uuid.uuid4().hex[:8]}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(make_url(ADMIN_URL).set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
