"""Aides des migrations Alembic du schéma `app` (BE-02).

Séparées de `migrations/env.py` pour pouvoir se tester seules.
"""

import os
from collections.abc import Mapping

# Compte `svc_app` : propriétaire du schéma `app` et seul à y créer des tables (ADR-024).
# Variable d'environnement, jamais un fichier : l'adresse contient le mot de passe.
URL_VARIABLE = "APP_DATABASE_URL"

# Sans base (génération du SQL avec --sql), Alembic n'a besoin que du dialecte.
OFFLINE_URL = "postgresql+psycopg://"

# Crée le schéma `app` s'il manque, sans toucher à un schéma existant.
# `CREATE SCHEMA IF NOT EXISTS` exigerait le droit de création sur la base, que `svc_app` n'a pas :
# sur le poste, le schéma est créé vide à l'initialisation (db/postgres/init).
ENSURE_SCHEMA_SQL = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app') "
    "THEN CREATE SCHEMA app; END IF; END $$"
)


class MissingDatabaseUrl(RuntimeError):
    """L'adresse de la base n'est pas fournie : la migration ne devine pas où écrire."""


def database_url(environ: Mapping[str, str] | None = None) -> str:
    """Adresse SQLAlchemy de la base, lue dans l'environnement.

    Forme : `postgresql+psycopg://svc_app:…@hôte:port/base`.
    """
    value = (os.environ if environ is None else environ).get(URL_VARIABLE, "")
    if not value:
        raise MissingDatabaseUrl(
            f"Variable {URL_VARIABLE} absente : "
            "python scripts/dev/dev.py db-migrate-app la construit depuis .env."
        )
    return value
