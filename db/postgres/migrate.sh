#!/bin/sh
# Applique, dans l'ordre alphabétique, les migrations SQL du dossier /migrations.
# - Chaque fichier n'est appliqué qu'une fois, dans une transaction unique (tout ou rien).
# - L'empreinte SHA-256 de chaque fichier appliqué est conservée : modifier un fichier déjà appliqué
#   est refusé (une migration appliquée ne se réécrit jamais : on en ajoute une nouvelle).
# - Nom de fichier imposé : NNNN_description_en_minuscules.sql
# Connexion par les variables PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE.
# Exécution : docker compose run --rm db-migrate   (ou : python scripts/dev/dev.py db-migrate)
set -eu

MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"

psql -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE SCHEMA IF NOT EXISTS ops;
CREATE TABLE IF NOT EXISTS ops.schema_migrations (
    filename   text PRIMARY KEY,
    sha256     text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

applied=0
skipped=0
files=$(find "$MIGRATIONS_DIR" -maxdepth 1 -type f -name '*.sql' | sort)
if [ -z "$files" ]; then
  echo "Aucune migration trouvée dans $MIGRATIONS_DIR" >&2
  exit 1
fi

for f in $files; do
  name=$(basename "$f")
  case "$name" in
    [0-9][0-9][0-9][0-9]_[a-z0-9_]*.sql) ;;
    *) echo "ERREUR : nom de migration invalide : $name (attendu : NNNN_description.sql)" >&2; exit 1 ;;
  esac
  sum=$(sha256sum "$f" | cut -d' ' -f1)
  known=$(psql -At -v ON_ERROR_STOP=1 -c "SELECT sha256 FROM ops.schema_migrations WHERE filename = '$name'")
  if [ -n "$known" ]; then
    if [ "$known" != "$sum" ]; then
      echo "ERREUR : $name a été modifiée après son application. Annuler la modification et créer une nouvelle migration." >&2
      exit 1
    fi
    skipped=$((skipped + 1))
    continue
  fi
  echo "Application de $name"
  psql -v ON_ERROR_STOP=1 -q -1 \
    -f "$f" \
    -c "INSERT INTO ops.schema_migrations (filename, sha256) VALUES ('$name', '$sum')"
  applied=$((applied + 1))
done

echo "Migrations : $applied appliquée(s), $skipped déjà présente(s)."
