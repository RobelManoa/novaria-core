"""Migrations Alembic du schéma `app` (BE-02), sans base : le SQL généré est comparé au modèle.

Le même contrôle contre un vrai PostgreSQL est dans `tests/integration/test_migration_postgres.py`.
"""

import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.migration import (
    ENSURE_SCHEMA_SQL,
    OFFLINE_URL,
    URL_VARIABLE,
    MissingDatabaseUrl,
    database_url,
)
from app.models import SCHEMA, User

SERVICE = Path(__file__).resolve().parents[2]
ADRESSE = "postgresql+psycopg://utilisateur:motdepasse@hote/base"


def configuration() -> Config:
    config = Config(str(SERVICE / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


def sql_genere(sens: str = "upgrade", plage: str = "head") -> str:
    config = configuration()
    config.output_buffer = io.StringIO()
    getattr(command, sens)(config, plage, sql=True)
    return config.output_buffer.getvalue()


def lignes_de_table(texte: str) -> set[str]:
    """Colonnes et contraintes d'un CREATE TABLE, sans virgule finale ni espace superflu."""
    bloc = texte[texte.index("CREATE TABLE app.users (") :]
    bloc = bloc[: bloc.index("\n)")]
    return {ligne.strip().rstrip(",").strip() for ligne in bloc.splitlines()[1:] if ligne.strip()}


def test_there_is_one_linear_history_starting_at_0001():
    scripts = ScriptDirectory.from_config(configuration())
    assert scripts.get_heads() == ["0001"]
    assert scripts.get_bases() == ["0001"]
    revisions = list(scripts.walk_revisions())
    assert [r.revision for r in revisions] == ["0001"]
    assert revisions[0].down_revision is None
    assert revisions[0].doc.startswith("Schéma app")


def test_every_revision_file_is_named_after_its_revision_number():
    for fichier in (SERVICE / "migrations" / "versions").glob("*.py"):
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+\.py", fichier.name), fichier.name
        contenu = fichier.read_text(encoding="utf-8")
        assert f'revision: str = "{fichier.name[:4]}"' in contenu


def test_the_offline_sql_creates_the_schema_the_version_table_and_the_users_table():
    sql = sql_genere()
    versions = sql.index("CREATE TABLE app.alembic_version")
    assert sql.index(ENSURE_SCHEMA_SQL) < versions < sql.index("CREATE TABLE app.users")
    assert "INSERT INTO app.alembic_version (version_num) VALUES ('0001')" in sql
    assert sql.startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;"), "tout ou rien"
    assert "public." not in sql, "svc_app ne peut rien créer dans public"


def test_the_version_table_lives_in_the_app_schema():
    sql = sql_genere()
    assert "CREATE TABLE app.alembic_version" in sql
    assert "CREATE TABLE alembic_version" not in sql


def test_the_migration_creates_exactly_the_columns_and_constraints_of_the_model():
    modele = str(CreateTable(User.__table__).compile(dialect=postgresql.dialect()))
    assert lignes_de_table(sql_genere()) == lignes_de_table(modele)


def test_the_migration_carries_the_comments_of_the_model():
    sql = sql_genere()
    table = User.__table__
    assert f"COMMENT ON TABLE app.users IS '{table.comment.replace(chr(39), chr(39) * 2)}'" in sql
    for colonne in table.columns:
        commentaire = colonne.comment.replace("'", "''")
        assert f"COMMENT ON COLUMN app.users.{colonne.name} IS '{commentaire}'" in sql


def test_the_migration_touches_only_the_app_schema():
    sql = sql_genere()
    assert set(re.findall(r"\b(\w+)\.(?:users|alembic_version)\b", sql)) == {SCHEMA}
    for autre in ("dwh.", "alertes.", "ops."):
        assert autre not in sql


def test_the_downgrade_drops_the_table_and_keeps_the_schema():
    sql = sql_genere("downgrade", "0001:base")
    assert "DROP TABLE app.users" in sql
    assert "DROP SCHEMA" not in sql
    assert "DELETE FROM app.alembic_version" in sql


def test_the_schema_guard_creates_nothing_when_the_schema_exists():
    assert "IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app')" in ENSURE_SCHEMA_SQL
    assert "CREATE SCHEMA app;" in ENSURE_SCHEMA_SQL
    # Pas de `CREATE SCHEMA IF NOT EXISTS` : il exigerait le droit de création sur la base.
    assert "CREATE SCHEMA IF NOT EXISTS" not in ENSURE_SCHEMA_SQL
    assert f"'{SCHEMA}'" in ENSURE_SCHEMA_SQL


def test_the_database_url_comes_from_the_environment_only():
    assert URL_VARIABLE == "APP_DATABASE_URL"
    assert database_url({URL_VARIABLE: ADRESSE}) == ADRESSE
    with pytest.raises(MissingDatabaseUrl) as erreur:
        database_url({})
    assert URL_VARIABLE in str(erreur.value)
    with pytest.raises(MissingDatabaseUrl):
        database_url({URL_VARIABLE: ""})


def test_the_database_url_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv(URL_VARIABLE, ADRESSE)
    assert database_url() == ADRESSE


def test_the_offline_dialect_is_postgresql_with_psycopg():
    assert OFFLINE_URL.startswith("postgresql+psycopg://")


def test_an_online_run_without_url_or_connection_stops_before_touching_anything(monkeypatch):
    monkeypatch.delenv(URL_VARIABLE, raising=False)
    with pytest.raises(MissingDatabaseUrl):
        command.upgrade(configuration(), "head")


def test_no_secret_is_written_in_the_alembic_configuration():
    contenu = (SERVICE / "alembic.ini").read_text(encoding="utf-8")
    assert "sqlalchemy.url" not in contenu
    assert not re.search(r"://\w+:[^@\s]+@", contenu)
