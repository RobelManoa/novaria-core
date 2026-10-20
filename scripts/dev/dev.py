#!/usr/bin/env python3
"""Commandes du poste de travail Novaria Core, identiques sous Windows et sous Linux (ADR-026).

Bibliothèque standard uniquement. Aide : python scripts/dev/dev.py --help
(Windows : `py -3 scripts/dev/dev.py ...` fonctionne aussi.)
"""
from __future__ import annotations

import argparse
import os
import platform
import secrets
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
PLACEHOLDER = "change-me-local"
INIT_ENV_HINT = "Créer d'abord le fichier .env :  python scripts/dev/dev.py init-env"


class DevError(Exception):
    """Erreur attendue, affichée sans trace d'appel."""


# --------------------------------------------------------------------------- fichier .env
def generate_env(example_text: str) -> tuple[str, int]:
    """Remplace chaque valeur « change-me-local » par un secret aléatoire (valeurs jamais affichées).

    Rend le texte du fichier et le nombre de secrets générés.
    """
    lines = []
    generated = 0
    for line in example_text.splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#") and value.startswith(PLACEHOLDER):
            size = 48 if key == "JWT_SECRET" else 24
            line = f"{key}={secrets.token_urlsafe(size)}"
            generated += 1
        lines.append(line)
    return "\n".join(lines) + "\n", generated


def parse_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def cmd_init_env(args: argparse.Namespace) -> int:
    if ENV_FILE.exists() and not args.force:
        print(f"{ENV_FILE.name} existe déjà : rien à faire (--force pour le recréer ; les bases déjà "
              "initialisées gardent leurs anciens mots de passe, voir db-reset).")
        return 0
    content, generated = generate_env(ENV_EXAMPLE.read_text(encoding="utf-8"))
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(ENV_FILE, flags, 0o600)  # lecture réservée au propriétaire (sans effet sous Windows)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print(f"{ENV_FILE.name} créé : {generated} secrets aléatoires générés. "
          "Les valeurs ne sont pas affichées et le fichier n'est jamais versionné.")
    return 0


# --------------------------------------------------------------------------- appels à Docker
def require_docker() -> None:
    if shutil.which("docker") is None:
        raise DevError("Docker est introuvable. Installer Docker Desktop (Windows) ou Docker Engine (Linux), "
                       "puis relancer : python scripts/dev/dev.py check-tools")


def require_env() -> None:
    if not ENV_FILE.exists():
        raise DevError(INIT_ENV_HINT)


def compose(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Lance `docker compose ...` à la racine du dépôt (sans shell : même comportement sous Windows)."""
    require_docker()
    return subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, check=check, capture_output=capture,
        text=True, encoding="utf-8", errors="replace",
    )


def run_compose_step(*args: str) -> int:
    require_env()
    return compose(*args, check=False).returncode


def cmd_up(_: argparse.Namespace) -> int:
    code = run_compose_step("up", "--build", "-d")
    if code == 0:
        print("API : http://localhost:8000/docs   ·   Front-end : http://localhost:8080")
    return code


def cmd_down(_: argparse.Namespace) -> int:
    return run_compose_step("down")


def cmd_db_up(_: argparse.Namespace) -> int:
    code = run_compose_step("up", "-d", "--wait", "postgres", "mongo")
    if code != 0:
        return code
    return cmd_db_migrate(argparse.Namespace())


def cmd_db_migrate(_: argparse.Namespace) -> int:
    return run_compose_step("run", "--rm", "db-migrate")


def cmd_ps(_: argparse.Namespace) -> int:
    return run_compose_step("ps", "--all")


def cmd_logs(args: argparse.Namespace) -> int:
    return run_compose_step("logs", "--tail", "100", "-f", *args.services)


def cmd_psql(_: argparse.Namespace) -> int:
    return run_compose_step("exec", "postgres", "sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"')


def cmd_mongosh(_: argparse.Namespace) -> int:
    return run_compose_step(
        "exec", "mongo", "sh", "-c",
        'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
        '--authenticationDatabase admin "$MONGO_DB"',
    )


def cmd_db_status(_: argparse.Namespace) -> int:
    code = run_compose_step("ps", "postgres", "mongo")
    if code != 0:
        return code
    return run_compose_step(
        "exec", "-T", "postgres", "sh", "-c",
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '
        '"SELECT filename, applied_at FROM ops.schema_migrations ORDER BY filename"',
    )


def cmd_backup(_: argparse.Namespace) -> int:
    for service in ("backup-postgres", "backup-mongo"):
        code = run_compose_step("--profile", "ops", "run", "--rm", service, "backup")
        if code != 0:
            return code
    print("Sauvegardes dans le dossier backups/ (ignoré par Git).")
    return 0


def cmd_restore_check(args: argparse.Namespace) -> int:
    """« latest » vérifie les deux bases ; un nom de fichier ne vérifie que la base correspondante."""
    services = ["backup-postgres", "backup-mongo"]
    if args.target.endswith(".dump"):
        services = ["backup-postgres"]
    elif args.target.endswith(".archive.gz"):
        services = ["backup-mongo"]
    for service in services:
        code = run_compose_step("--profile", "ops", "run", "--rm", service, "restore-check", args.target)
        if code != 0:
            return code
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """Remplace les données locales par celles d'une sauvegarde (après confirmation)."""
    require_env()
    if not args.yes:
        print("ATTENTION : les tables PostgreSQL et les collections MongoDB actuelles seront REMPLACÉES "
              "par celles de la sauvegarde. Le backend et le front-end sont arrêtés pendant l'opération.")
        if input("Taper « restaurer » pour confirmer : ").strip().lower() != "restaurer":
            print("Annulé.")
            return 1
    compose("stop", "backend", "frontend", check=False)
    for service, target in (("backup-postgres", args.postgres), ("backup-mongo", args.mongo)):
        code = run_compose_step("--profile", "ops", "run", "--rm", "-e", "CONFIRM_RESTORE=yes",
                                service, "restore", target)
        if code != 0:
            return code
    print("Restauration terminée. Relancer l'application :  python scripts/dev/dev.py up")
    return 0


def cmd_db_reset(args: argparse.Namespace) -> int:
    require_env()
    if not args.yes:
        print("ATTENTION : cette commande SUPPRIME les données locales de PostgreSQL et de MongoDB "
              "(les sauvegardes du dossier backups/ sont conservées).")
        if input("Taper « effacer » pour confirmer : ").strip().lower() != "effacer":
            print("Annulé.")
            return 1
    return compose("down", "-v", check=False).returncode


# --------------------------------------------------------------------------- vérification des bases
# (service, libellé, commande exécutée dans le conteneur, succès attendu)
# Les mots de passe sont lus dans l'environnement du conteneur : jamais affichés.
Check = tuple[str, str, str, bool]


def pg_as(role: str, password_var: str, sql: str) -> str:
    return (f'PGPASSWORD="${password_var}" psql -h postgres -U {role} -d "$POSTGRES_DB" '
            f'-v ON_ERROR_STOP=1 -Atq -c "{sql}"')


def mongo_as(user: str, password_var: str, js: str) -> str:
    return (f'mongosh --quiet -u {user} -p "${password_var}" --authenticationDatabase "$MONGO_DB" '
            f'"$MONGO_DB" --eval "{js}"')


def build_checks() -> list[Check]:
    admin_pg = ('PGPASSWORD="$POSTGRES_PASSWORD" psql -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                '-v ON_ERROR_STOP=1 -Atq -c "{sql}"')
    schemas = ("SELECT 1/(count(*) = 4)::int FROM information_schema.schemata "
               "WHERE schema_name IN ('app','dwh','alertes','ops')")
    migrations = "SELECT 1/(count(*) >= 5)::int FROM ops.schema_migrations"
    return [
        ("postgres", "administrateur : 4 schémas présents", admin_pg.format(sql=schemas), True),
        ("postgres", "administrateur : migrations appliquées", admin_pg.format(sql=migrations), True),
        ("postgres", "traitement lit l'entrepôt (dwh)",
         pg_as("svc_traitement", "PG_PASSWORD_TRAITEMENT", "SELECT count(*) FROM dwh.dim_road_segment"), True),
        ("postgres", "traitement ne lit PAS les alertes",
         pg_as("svc_traitement", "PG_PASSWORD_TRAITEMENT", "SELECT count(*) FROM alertes.alert"), False),
        ("postgres", "alerte lit ses règles",
         pg_as("svc_alerte", "PG_PASSWORD_ALERTE", "SELECT count(*) FROM alertes.alert_rule"), True),
        ("postgres", "alerte ne lit PAS l'entrepôt",
         pg_as("svc_alerte", "PG_PASSWORD_ALERTE", "SELECT count(*) FROM dwh.dim_date"), False),
        ("postgres", "lecture seule : lit l'entrepôt",
         pg_as("svc_lecture", "PG_PASSWORD_LECTURE", "SELECT count(*) FROM dwh.dim_date"), True),
        ("postgres", "lecture seule : n'écrit PAS",
         pg_as("svc_lecture", "PG_PASSWORD_LECTURE", "DELETE FROM dwh.dim_source WHERE false"), False),
        ("postgres", "API métier n'accède PAS à l'entrepôt",
         pg_as("svc_app", "PG_PASSWORD_APP", "SELECT count(*) FROM dwh.dim_date"), False),
        ("mongo", "administrateur : 6 collections",
         'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
         '--authenticationDatabase admin "$MONGO_DB" --eval '
         '"if (db.getCollectionNames().length < 6) throw new Error(\'collections manquantes\')"', True),
        ("mongo", "administrateur : index de durée de vie sur raw_events",
         'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
         '--authenticationDatabase admin "$MONGO_DB" --eval '
         '"if (!db.raw_events.getIndexes().some(i => i.expireAfterSeconds)) throw new Error(\'TTL absent\')"', True),
        ("mongo", "collecte lit raw_events", mongo_as("svc_collecte", "MONGO_PASSWORD_COLLECTE", "db.raw_events.findOne()"), True),
        ("mongo", "collecte ne lit PAS audit_logs", mongo_as("svc_collecte", "MONGO_PASSWORD_COLLECTE", "db.audit_logs.findOne()"), False),
        ("mongo", "traitement lit raw_events", mongo_as("svc_traitement", "MONGO_PASSWORD_TRAITEMENT", "db.raw_events.findOne()"), True),
        ("mongo", "traitement ne lit PAS model_runs", mongo_as("svc_traitement", "MONGO_PASSWORD_TRAITEMENT", "db.model_runs.findOne()"), False),
        ("mongo", "réponse lit audit_logs", mongo_as("svc_reponse", "MONGO_PASSWORD_REPONSE", "db.audit_logs.findOne()"), True),
        ("mongo", "réponse ne lit PAS raw_events", mongo_as("svc_reponse", "MONGO_PASSWORD_REPONSE", "db.raw_events.findOne()"), False),
        ("mongo", "backend lit usage_stats", mongo_as("svc_backend", "MONGO_PASSWORD_BACKEND", "db.usage_stats.findOne()"), True),
        ("mongo", "backend ne lit PAS raw_events", mongo_as("svc_backend", "MONGO_PASSWORD_BACKEND", "db.raw_events.findOne()"), False),
        ("mongo", "ML lit model_runs", mongo_as("svc_ml", "MONGO_PASSWORD_ML", "db.model_runs.findOne()"), True),
        ("mongo", "ML ne lit PAS audit_logs", mongo_as("svc_ml", "MONGO_PASSWORD_ML", "db.audit_logs.findOne()"), False),
    ]


def cmd_db_check(_: argparse.Namespace) -> int:
    require_env()
    failures = 0
    for service, label, command, expect_success in build_checks():
        result = compose("exec", "-T", service, "sh", "-c", command, check=False, capture=True)
        succeeded = result.returncode == 0
        ok = succeeded == expect_success
        failures += 0 if ok else 1
        print(f"  [{'OK' if ok else 'KO'}] {service:<8} {label}")
    print("Toutes les vérifications passent." if failures == 0 else f"{failures} vérification(s) en échec.")
    return 0 if failures == 0 else 1


# --------------------------------------------------------------------------- vérification du poste
def tool_version(command: Sequence[str]) -> str | None:
    executable = shutil.which(command[0])
    if executable is None:
        return None
    try:
        out = subprocess.run([executable, *command[1:]], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else "présent"


INSTALL_HINTS = {
    "Windows": {
        "docker": "Docker Desktop (backend WSL 2) : https://docs.docker.com/desktop/setup/install/windows-install/",
        "git": "Git for Windows : https://git-scm.com/download/win",
        "python": "Python 3.12 : https://www.python.org/downloads/ (cocher « Add python.exe to PATH »)",
        "node": "Node.js 22 LTS : https://nodejs.org/",
        "gh": "GitHub CLI : winget install --id GitHub.cli",
    },
    "Linux": {
        "docker": "Docker Engine : https://docs.docker.com/engine/install/ puis `sudo usermod -aG docker $USER`",
        "git": "sudo apt install git",
        "python": "Python 3.12 : sudo apt install python3.12 python3.12-venv",
        "node": "Node.js 22 LTS : https://nodejs.org/ ou nvm",
        "gh": "GitHub CLI : https://github.com/cli/cli/blob/trunk/docs/install_linux.md",
    },
}


def cmd_check_tools(_: argparse.Namespace) -> int:
    system = platform.system() if platform.system() in INSTALL_HINTS else "Linux"
    hints = INSTALL_HINTS[system]
    python_ok = sys.version_info >= (3, 12)
    rows = [
        ("python", f"Python {platform.python_version()}" if python_ok else None),
        ("docker", tool_version(["docker", "--version"])),
        ("compose", tool_version(["docker", "compose", "version"])),
        ("git", tool_version(["git", "--version"])),
        ("node", tool_version(["node", "--version"])),
        ("gh", tool_version(["gh", "--version"])),
    ]
    missing = 0
    for name, version in rows:
        hint_key = "docker" if name == "compose" else name
        if version:
            print(f"  [OK] {name:<8} {version}")
        else:
            missing += 1
            print(f"  [KO] {name:<8} manquant ou trop ancien → {hints[hint_key]}")
    return 0 if missing == 0 else 1


# --------------------------------------------------------------------------- ligne de commande
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dev.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.set_defaults(func=func)
        return p

    add("check-tools", cmd_check_tools, "vérifie les outils installés sur le poste")
    add("init-env", cmd_init_env, "crée .env avec des mots de passe aléatoires").add_argument(
        "--force", action="store_true", help="recrée .env même s'il existe")
    add("up", cmd_up, "démarre tout : bases, migrations, backend, frontend")
    add("down", cmd_down, "arrête tout (les données sont conservées)")
    add("db-up", cmd_db_up, "démarre PostgreSQL et MongoDB, puis applique les migrations")
    add("db-migrate", cmd_db_migrate, "applique les migrations SQL en attente")
    add("db-status", cmd_db_status, "état des bases et des migrations")
    add("db-check", cmd_db_check, "vérifie rôles, droits, collections et index")
    add("psql", cmd_psql, "ouvre psql dans le conteneur PostgreSQL (administrateur)")
    add("mongosh", cmd_mongosh, "ouvre mongosh dans le conteneur MongoDB (administrateur)")
    add("backup", cmd_backup, "sauvegarde PostgreSQL et MongoDB dans backups/")
    restore = add("restore-check", cmd_restore_check, "restaure une sauvegarde dans une base jetable et compare")
    restore.add_argument("target", nargs="?", default="latest", help="nom du fichier ou « latest »")
    rest = add("restore", cmd_restore, "REMPLACE les données locales par une sauvegarde (confirmation demandée)")
    rest.add_argument("--postgres", default="latest", help="fichier PostgreSQL ou « latest »")
    rest.add_argument("--mongo", default="latest", help="fichier MongoDB ou « latest »")
    rest.add_argument("--yes", action="store_true", help="sans demande de confirmation")
    reset = add("db-reset", cmd_db_reset, "SUPPRIME les données locales des deux bases")
    reset.add_argument("--yes", action="store_true", help="sans demande de confirmation")
    add("ps", cmd_ps, "état des conteneurs")
    logs = add("logs", cmd_logs, "suit les journaux")
    logs.add_argument("services", nargs="*", help="services (tous par défaut)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DevError as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
