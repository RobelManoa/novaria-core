"""`alembic upgrade head` sur une base vide, contre un vrai PostgreSQL (BE-02).

Ignoré sans `NOVARIA_TEST_POSTGRES_ADMIN_URL` : adresse SQLAlchemy du compte administrateur d'un
PostgreSQL local, par exemple `postgresql+psycopg://novaria_admin:…@127.0.0.1:5432/novaria`
(docs/03-donnees/base-de-donnees-locale.md). Chaque test crée sa propre base vide et la supprime
ensuite : la base du projet n'est pas touchée.
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError

from app.models import SCHEMA, Base

SERVICE = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get("NOVARIA_TEST_POSTGRES_ADMIN_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="NOVARIA_TEST_POSTGRES_ADMIN_URL absent : PostgreSQL local requis"
)

EMPREINTE = "$argon2id$v=19$m=65536,t=3,p=4$exemple$exemple"
INSERTION = text(
    "INSERT INTO app.users (username, password_hash, role) "
    "VALUES (:username, :password_hash, :role) RETURNING user_id"
)


def alembic_on(connection) -> Config:
    config = Config(str(SERVICE / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def empty_database():
    """Une base vide (aucun schéma `app`), créée pour le test puis supprimée."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    name = f"novaria_test_be02_{uuid.uuid4().hex[:8]}"
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


def upgrade(engine, revision: str = "head") -> None:
    with engine.begin() as connection:
        command.upgrade(alembic_on(connection), revision)


def downgrade(engine, revision: str) -> None:
    with engine.begin() as connection:
        command.downgrade(alembic_on(connection), revision)


def tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def insert(connection, **valeurs):
    champs = {"username": "alice", "password_hash": EMPREINTE, "role": "viewer", **valeurs}
    return connection.execute(INSERTION, champs)


def test_upgrade_head_creates_the_schema_and_the_tables_on_an_empty_database(empty_database):
    assert SCHEMA not in inspect(empty_database).get_schema_names()
    upgrade(empty_database)
    assert SCHEMA in inspect(empty_database).get_schema_names()
    assert tables(empty_database) == {"users", "alembic_version"}
    with empty_database.connect() as connection:
        versions = connection.execute(text("SELECT version_num FROM app.alembic_version"))
        assert versions.scalars().all() == ["0001"]


def test_the_created_columns_are_the_columns_of_the_model(empty_database):
    upgrade(empty_database)
    colonnes = {c["name"]: c for c in inspect(empty_database).get_columns("users", schema=SCHEMA)}
    assert list(colonnes) == [
        "user_id",
        "username",
        "password_hash",
        "role",
        "is_active",
        "created_at",
    ]
    assert all(not c["nullable"] for c in colonnes.values())
    assert colonnes["username"]["type"].length == 64
    assert colonnes["created_at"]["type"].timezone is True
    assert colonnes["role"]["comment"] == "Droit d'accès : viewer, operator ou admin."


def test_the_database_has_no_difference_with_the_models_after_upgrade(empty_database):
    upgrade(empty_database)
    with empty_database.connect() as connection:
        contexte = MigrationContext.configure(
            connection,
            opts={
                "target_metadata": Base.metadata,
                "include_schemas": True,
                "version_table_schema": SCHEMA,
                "compare_type": True,
                "include_name": lambda name, type_, parent: (
                    name == SCHEMA if type_ == "schema" else True
                ),
            },
        )
        assert compare_metadata(contexte, Base.metadata) == []


def test_running_upgrade_twice_changes_nothing(empty_database):
    upgrade(empty_database)
    upgrade(empty_database)
    assert tables(empty_database) == {"users", "alembic_version"}
    with empty_database.connect() as connection:
        total = connection.execute(text("SELECT count(*) FROM app.alembic_version"))
        assert total.scalar() == 1


def test_downgrade_removes_the_table_and_a_new_upgrade_brings_it_back(empty_database):
    upgrade(empty_database)
    downgrade(empty_database, "base")
    assert tables(empty_database) == {"alembic_version"}
    assert SCHEMA in inspect(empty_database).get_schema_names(), "le schéma reste : initialisation"
    upgrade(empty_database)
    assert "users" in tables(empty_database)


def test_an_existing_empty_schema_is_used_as_it_is(empty_database):
    """Cas du poste local : l'initialisation a déjà créé le schéma `app` vide (db/postgres/init)."""
    with empty_database.begin() as connection:
        connection.execute(text("CREATE SCHEMA app"))
    upgrade(empty_database)
    assert tables(empty_database) == {"users", "alembic_version"}


def test_the_database_fills_identifier_status_and_creation_date(empty_database):
    upgrade(empty_database)
    with empty_database.begin() as connection:
        identifiant = insert(connection).scalar_one()
        ligne = connection.execute(
            text(
                "SELECT is_active, created_at, now() - created_at < interval '1 minute' "
                "FROM app.users"
            )
        ).one()
    assert isinstance(identifiant, uuid.UUID)
    assert ligne[0] is True
    assert ligne[1].tzinfo is not None
    assert ligne[2] is True


@pytest.mark.parametrize(
    ("valeurs", "message"),
    [
        ({"username": "ab"}, "ck_users_username_format"),
        ({"username": "Alice"}, "ck_users_username_format"),
        ({"username": "a b c"}, "ck_users_username_format"),
        ({"username": "x" * 65}, "value too long"),
        ({"role": "root"}, "ck_users_role_valid"),
        ({"role": "ADMIN"}, "ck_users_role_valid"),
        ({"password_hash": "motdepasse-en-clair"}, "ck_users_password_hash_is_a_hash"),
        ({"password_hash": ""}, "ck_users_password_hash_is_a_hash"),
        ({"username": None}, 'null value in column "username"'),
        ({"password_hash": None}, 'null value in column "password_hash"'),
        ({"role": None}, 'null value in column "role"'),
    ],
)
def test_the_constraints_refuse_invalid_rows(empty_database, valeurs, message):
    upgrade(empty_database)
    with pytest.raises((IntegrityError, DataError)) as erreur, empty_database.begin() as connection:
        insert(connection, **valeurs)
    assert message in str(erreur.value)


def test_two_users_cannot_share_a_username(empty_database):
    upgrade(empty_database)
    with empty_database.begin() as connection:
        insert(connection)
    with pytest.raises(IntegrityError) as erreur, empty_database.begin() as connection:
        insert(connection, role="admin")
    assert "uq_users_username" in str(erreur.value)


def test_the_three_roles_are_accepted(empty_database):
    upgrade(empty_database)
    with empty_database.begin() as connection:
        for numero, role in enumerate(("viewer", "operator", "admin")):
            insert(connection, username=f"user{numero}", role=role)
        assert connection.execute(text("SELECT count(*) FROM app.users")).scalar() == 3
