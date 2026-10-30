"""Environnement Alembic du schéma `app` (BE-02).

Deux modes : en ligne (connexion à la base) et hors ligne (`--sql` : écrit le SQL sans se
connecter). La table de versions est dans le schéma `app` : `svc_app` ne peut rien créer dans
`public` (db/postgres/init). Une connexion déjà ouverte, passée par
`config.attributes["connection"]`, est utilisée telle quelle (tests).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from app.db.migration import ENSURE_SCHEMA_SQL, OFFLINE_URL, database_url
from app.models import SCHEMA, Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

COMMON = {
    "target_metadata": Base.metadata,
    "version_table_schema": SCHEMA,
    "include_schemas": True,
    # Seul le schéma `app` est suivi ici : `dwh`, `alertes` et `ops` ont leur propre exécuteur
    # (ADR-024).
    "include_name": lambda name, type_, parent_names: type_ != "schema" or name == SCHEMA,
}


def run_migrations() -> None:
    with context.begin_transaction():
        # D'abord le schéma : la table de versions y vit, il doit exister (base non initialisée).
        context.execute(text(ENSURE_SCHEMA_SQL))
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=OFFLINE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"}, **COMMON
    )
    run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, **COMMON)
        run_migrations()
        return
    engine = create_engine(database_url())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, **COMMON)
            run_migrations()
            connection.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
