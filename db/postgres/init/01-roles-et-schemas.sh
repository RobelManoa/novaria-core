#!/bin/bash
# Exécuté UNE SEULE FOIS par l'image PostgreSQL, au premier démarrage d'un volume vide
# (dossier /docker-entrypoint-initdb.d). Crée les schémas et un rôle de connexion par service.
# Les tables ne sont pas créées ici : elles viennent des migrations (db/postgres/migrate.sh).
# Compatible avec une exécution directe comme avec le « sourcing » de l'image : pas de `exit`.
set -eu

: "${POSTGRES_USER:?variable manquante}"
: "${POSTGRES_DB:?variable manquante}"
: "${PG_PASSWORD_APP:?variable manquante}"
: "${PG_PASSWORD_TRAITEMENT:?variable manquante}"
: "${PG_PASSWORD_ALERTE:?variable manquante}"
: "${PG_PASSWORD_LECTURE:?variable manquante}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v dbname="$POSTGRES_DB" \
  -v pw_app="$PG_PASSWORD_APP" \
  -v pw_traitement="$PG_PASSWORD_TRAITEMENT" \
  -v pw_alerte="$PG_PASSWORD_ALERTE" \
  -v pw_lecture="$PG_PASSWORD_LECTURE" <<'SQL'

-- Rôles de service : connexion seulement, aucun droit d'administration.
CREATE ROLE svc_app        LOGIN PASSWORD :'pw_app';        -- API métier (schéma app, migrations Alembic)
CREATE ROLE svc_traitement LOGIN PASSWORD :'pw_traitement'; -- service de traitement (schéma dwh)
CREATE ROLE svc_alerte     LOGIN PASSWORD :'pw_alerte';     -- service d'alerte usager (schéma alertes)
CREATE ROLE svc_lecture    LOGIN PASSWORD :'pw_lecture';    -- lecture seule (API de consultation, analyses)

-- La base n'est ouverte qu'aux rôles de service ; les dates et heures sont stockées en UTC (ADR-012).
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO svc_app, svc_traitement, svc_alerte, svc_lecture;
ALTER DATABASE :"dbname" SET timezone TO 'UTC';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Un schéma par propriétaire de données (ADR-008, règle 1 : un service écrit seulement dans ses schémas).
CREATE SCHEMA app;      -- tables métier (utilisateurs, rôles) : créées par Alembic
CREATE SCHEMA dwh;      -- entrepôt décisionnel : écrit par le service de traitement
CREATE SCHEMA alertes;  -- alertes et file de publication : écrit par le service d'alerte
CREATE SCHEMA ops;      -- suivi des migrations : réservé à l'administrateur

-- app : le rôle de l'API crée et possède ses tables.
GRANT USAGE, CREATE ON SCHEMA app TO svc_app;

-- dwh : les tables sont créées par l'administrateur (migrations), les droits suivent automatiquement.
GRANT USAGE ON SCHEMA dwh TO svc_traitement, svc_lecture;
ALTER DEFAULT PRIVILEGES IN SCHEMA dwh GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO svc_traitement;
ALTER DEFAULT PRIVILEGES IN SCHEMA dwh GRANT USAGE, SELECT ON SEQUENCES TO svc_traitement;
ALTER DEFAULT PRIVILEGES IN SCHEMA dwh GRANT SELECT ON TABLES TO svc_lecture;

-- alertes : même principe pour le service d'alerte.
GRANT USAGE ON SCHEMA alertes TO svc_alerte, svc_lecture;
ALTER DEFAULT PRIVILEGES IN SCHEMA alertes GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO svc_alerte;
ALTER DEFAULT PRIVILEGES IN SCHEMA alertes GRANT USAGE, SELECT ON SEQUENCES TO svc_alerte;
ALTER DEFAULT PRIVILEGES IN SCHEMA alertes GRANT SELECT ON TABLES TO svc_lecture;

SQL

echo "Rôles et schémas créés (app, dwh, alertes, ops)."
