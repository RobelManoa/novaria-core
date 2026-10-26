#!/bin/sh
# Sauvegarde et vérification de restauration de MongoDB (ADR-024).
# Exécuté dans un conteneur éphémère :
#   docker compose --profile ops run --rm backup-mongo backup
#   docker compose --profile ops run --rm backup-mongo list
#   docker compose --profile ops run --rm backup-mongo restore-check [latest|NOM_DU_FICHIER]
#   docker compose --profile ops run --rm -e CONFIRM_RESTORE=yes backup-mongo restore [latest|NOM_DU_FICHIER]
# (ou : python scripts/dev/dev.py backup  /  restore-check  /  restore)
#
# backup         : mongodump (archive compressée), comptage des documents de chaque collection au moment
#                  de la sauvegarde (fichier .counts), rotation des anciennes sauvegardes.
# restore-check  : restaure l'archive dans une base jetable, compare les comptages au fichier .counts,
#                  puis supprime la base jetable. La base de travail n'est jamais modifiée.
# restore        : REMPLACE les collections de la base de travail par celles de la sauvegarde (validateurs et
#                  index compris ; utilisateurs et rôles, stockés dans la base admin, ne changent pas).
#                  Exige CONFIRM_RESTORE=yes ; arrêter le backend avant (dev.py restore le fait).
# Variables : MONGO_HOST, MONGO_PORT, MONGO_ROOT_USER, MONGO_ROOT_PASSWORD, MONGO_DB, BACKUP_KEEP.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups/mongo}"
KEEP="${BACKUP_KEEP:-7}"
HOST="${MONGO_HOST:-mongo}"
PORT="${MONGO_PORT:-27017}"
CHECK_DB="${MONGO_DB}_restore_check"
cmd="${1:-backup}"
WORK=$(mktemp -d)                      # fichiers de travail, supprimés en fin d'exécution
trap 'rm -rf "$WORK"' EXIT

AUTH="--host $HOST --port $PORT --username $MONGO_ROOT_USER --password $MONGO_ROOT_PASSWORD --authenticationDatabase admin"

# Lignes « collection|nombre de documents » de la base passée en argument, triées.
counts() {
  # shellcheck disable=SC2086
  mongosh $AUTH --quiet "$1" --eval 'db.getCollectionNames().sort().forEach(function (n) { print(n + "|" + db.getCollection(n).countDocuments({})); })'
}

latest_dump() {
  ls -1t "$BACKUP_DIR"/*.archive.gz 2>/dev/null | head -n 1
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
    out="$BACKUP_DIR/${MONGO_DB}_${ts}.archive.gz"
    # shellcheck disable=SC2086
    mongodump $AUTH --db "$MONGO_DB" --archive="$out" --gzip --quiet
    counts "$MONGO_DB" > "$out.counts"
    chmod a+rw "$out" "$out.counts"
    chmod a+rwx "$BACKUP_DIR" "$(dirname "$BACKUP_DIR")"
    echo "Sauvegarde créée : $(basename "$out") ($(wc -c < "$out") octets, $(wc -l < "$out.counts") collections comptées)"
    ls -1t "$BACKUP_DIR"/*.archive.gz | tail -n +"$((KEEP + 1))" | while read -r old; do
      rm -f "$old" "$old.counts"
      echo "Ancienne sauvegarde supprimée : $(basename "$old")"
    done
    ;;
  list)
    ls -lht "$BACKUP_DIR"/*.archive.gz 2>/dev/null || echo "Aucune sauvegarde dans $BACKUP_DIR"
    ;;
  restore-check)
    pick_file "${2:-latest}"
    echo "Vérification de $(basename "$file") dans la base jetable $CHECK_DB"
    status=0
    # shellcheck disable=SC2086
    mongorestore $AUTH --archive="$file" --gzip --quiet --drop \
      --nsFrom "${MONGO_DB}.*" --nsTo "${CHECK_DB}.*" || status=1
    if [ "$status" -eq 0 ]; then
      counts "$CHECK_DB" > "$WORK/restored.counts"
      if diff "$file.counts" "$WORK/restored.counts" > "$WORK/counts.diff"; then
        echo "OK : $(wc -l < "$WORK/restored.counts") collections restaurées, comptages identiques à ceux de la sauvegarde."
      else
        echo "KO : les comptages diffèrent (< sauvegarde, > restauration) :" >&2
        cat "$WORK/counts.diff" >&2
        status=1
      fi
    else
      echo "KO : la restauration a échoué." >&2
    fi
    # shellcheck disable=SC2086
    mongosh $AUTH --quiet --eval "db.getSiblingDB('$CHECK_DB').dropDatabase()" > /dev/null
    exit "$status"
    ;;
  restore)
    if [ "${CONFIRM_RESTORE:-}" != "yes" ]; then
      echo "ERREUR : la restauration remplace les données de $MONGO_DB ; relancer avec CONFIRM_RESTORE=yes." >&2
      exit 2
    fi
    pick_file "${2:-latest}"
    echo "Restauration de $(basename "$file") dans $MONGO_DB (les collections sont remplacées)"
    # shellcheck disable=SC2086
    mongorestore $AUTH --archive="$file" --gzip --quiet --drop --nsInclude "${MONGO_DB}.*"
    counts "$MONGO_DB" > "$WORK/restored.counts"
    if diff "$file.counts" "$WORK/restored.counts" > "$WORK/counts.diff"; then
      echo "OK : $(wc -l < "$WORK/restored.counts") collections restaurées, comptages identiques à ceux de la sauvegarde."
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
