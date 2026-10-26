#!/bin/sh
# Sauvegarde et vérification de restauration de PostgreSQL (ADR-024).
# Exécuté dans un conteneur éphémère :
#   docker compose --profile ops run --rm backup-postgres backup
#   docker compose --profile ops run --rm backup-postgres list
#   docker compose --profile ops run --rm backup-postgres restore-check [latest|NOM_DU_FICHIER]
#   docker compose --profile ops run --rm -e CONFIRM_RESTORE=yes backup-postgres restore [latest|NOM_DU_FICHIER]
# (ou : python scripts/dev/dev.py backup  /  restore-check  /  restore)
#
# backup         : pg_dump au format « custom », vérification de lisibilité de l'archive, comptage des lignes
#                  de chaque table au moment de la sauvegarde (fichier .counts), rotation des anciennes sauvegardes.
# restore-check  : restaure l'archive dans une base jetable, compare les comptages au fichier .counts,
#                  puis supprime la base jetable. La base de travail n'est jamais modifiée.
# restore        : REMPLACE les tables de la base de travail par celles de la sauvegarde (droits compris).
#                  Exige CONFIRM_RESTORE=yes ; arrêter le backend avant (dev.py restore le fait).
# Connexion par PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups/postgres}"
KEEP="${BACKUP_KEEP:-7}"
CHECK_DB="${CHECK_DB:-novaria_restore_check}"
cmd="${1:-backup}"
WORK=$(mktemp -d)                      # fichiers de travail, supprimés en fin d'exécution
trap 'rm -rf "$WORK"' EXIT

# Lignes « schéma.table|nombre de lignes » pour toutes les tables des schémas du projet.
counts() {
  psql -At -d "$1" -c "
    SELECT table_schema || '.' || table_name || '|' ||
           (xpath('/row/c/text()', query_to_xml(
              format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE' AND table_schema IN ('app', 'dwh', 'alertes', 'ops')
    ORDER BY 1"
}

latest_dump() {
  ls -1t "$BACKUP_DIR"/*.dump 2>/dev/null | head -n 1
}

# Choisit le fichier de sauvegarde (« latest » ou un nom) et vérifie que son fichier de comptage existe.
pick_file() {
  target="${1:-latest}"
  if [ "$target" = "latest" ]; then
    file=$(latest_dump)
  else
    file="$BACKUP_DIR/$(basename "$target")"
  fi
  if [ -z "${file:-}" ] || [ ! -f "$file" ]; then
    echo "ERREUR : aucune sauvegarde trouvée (${target})." >&2
    exit 1
  fi
  if [ ! -f "$file.counts" ]; then
    echo "ERREUR : fichier de comptage absent : $(basename "$file").counts" >&2
    exit 1
  fi
}

case "$cmd" in
  backup)
    mkdir -p "$BACKUP_DIR"
    ts=$(date -u +%Y%m%dT%H%M%SZ)
    out="$BACKUP_DIR/${PGDATABASE}_${ts}.dump"
    pg_dump --format=custom --no-owner --file "$out"      # droits inclus : une restauration les retrouve
    pg_restore --list "$out" > /dev/null          # l'archive doit être relisible
    counts "$PGDATABASE" > "$out.counts"
    chmod a+rw "$out" "$out.counts"
    chmod a+rwx "$BACKUP_DIR" "$(dirname "$BACKUP_DIR")"
    echo "Sauvegarde créée : $(basename "$out") ($(wc -c < "$out") octets, $(wc -l < "$out.counts") tables comptées)"
    # Rotation : on conserve les KEEP sauvegardes les plus récentes.
    ls -1t "$BACKUP_DIR"/*.dump | tail -n +"$((KEEP + 1))" | while read -r old; do
      rm -f "$old" "$old.counts"
      echo "Ancienne sauvegarde supprimée : $(basename "$old")"
    done
    ;;
  list)
    ls -lht "$BACKUP_DIR"/*.dump 2>/dev/null || echo "Aucune sauvegarde dans $BACKUP_DIR"
    ;;
  restore-check)
    pick_file "${2:-latest}"
    echo "Vérification de $(basename "$file") dans la base jetable $CHECK_DB"
    psql -d postgres -v ON_ERROR_STOP=1 -q -c "DROP DATABASE IF EXISTS $CHECK_DB" -c "CREATE DATABASE $CHECK_DB"
    status=0
    pg_restore --no-owner --exit-on-error -d "$CHECK_DB" "$file" || status=1
    if [ "$status" -eq 0 ]; then
      counts "$CHECK_DB" > "$WORK/restored.counts"
      if diff "$file.counts" "$WORK/restored.counts" > "$WORK/counts.diff"; then
        echo "OK : $(wc -l < "$WORK/restored.counts") tables restaurées, comptages identiques à ceux de la sauvegarde."
      else
        echo "KO : les comptages diffèrent (< sauvegarde, > restauration) :" >&2
        cat "$WORK/counts.diff" >&2
        status=1
      fi
    else
      echo "KO : la restauration a échoué." >&2
    fi
    psql -d postgres -q -c "DROP DATABASE IF EXISTS $CHECK_DB"
    exit "$status"
    ;;
  restore)
    if [ "${CONFIRM_RESTORE:-}" != "yes" ]; then
      echo "ERREUR : la restauration remplace les données de $PGDATABASE ; relancer avec CONFIRM_RESTORE=yes." >&2
      exit 2
    fi
    pick_file "${2:-latest}"
    echo "Restauration de $(basename "$file") dans $PGDATABASE (les tables sont recréées)"
    pg_restore --clean --if-exists --no-owner --exit-on-error -d "$PGDATABASE" "$file"
    counts "$PGDATABASE" > "$WORK/restored.counts"
    if diff "$file.counts" "$WORK/restored.counts" > "$WORK/counts.diff"; then
      echo "OK : $(wc -l < "$WORK/restored.counts") tables restaurées, comptages identiques à ceux de la sauvegarde."
    else
      echo "KO : les comptages diffèrent (< sauvegarde, > base) :" >&2
      cat "$WORK/counts.diff" >&2
      exit 1
    fi
    ;;
  *)
    echo "Usage : ops.sh backup | list | restore-check [latest|FICHIER] | restore [latest|FICHIER]" >&2
    exit 2
    ;;
esac
