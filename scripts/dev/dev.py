#!/usr/bin/env python3
"""Commandes du poste de travail Novaria Core, identiques sous Windows et sous Linux (ADR-026).

Bibliothèque standard uniquement. Aide : python scripts/dev/dev.py --help
(Windows : `py -3 scripts/dev/dev.py ...` fonctionne aussi.)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

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


def compose(*args: str, check: bool = True, capture: bool = False,
            input_text: str | None = None) -> subprocess.CompletedProcess:
    """Lance `docker compose ...` à la racine du dépôt (sans shell : même comportement sous Windows)."""
    require_docker()
    return subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, check=check, capture_output=capture, input=input_text,
        text=True, encoding="utf-8", errors="replace",
    )


def run_compose_step(*args: str) -> int:
    require_env()
    return compose(*args, check=False).returncode


# Conteneurs applicatifs de docker-compose.yml (hors bases, bus et tâches uniques).
APP_SERVICES = ("collecte", "traitement", "alerte", "reponse", "simulateur", "passerelle", "frontend")
HEALTH_WAIT_SECONDS = 90


class HealthCheck(NamedTuple):
    name: str
    port_variable: str  # variable de .env qui fixe le port publié sur 127.0.0.1
    default_port: int
    path: str
    label: str = ""  # précise ce que le chemin prouve quand il traverse plusieurs conteneurs


# Un /health par conteneur applicatif, plus deux chemins qui traversent la chaîne : l'API vue par la passerelle puis
# par le front-end (ils prouvent le routage et le proxy, pas seulement que chaque conteneur tourne).
HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck("collecte", "COLLECTE_PORT", 8001, "/api/v1/health"),
    HealthCheck("traitement", "TRAITEMENT_PORT", 8002, "/api/v1/health"),
    HealthCheck("alerte", "ALERTE_PORT", 8003, "/api/v1/health"),
    HealthCheck("reponse", "REPONSE_PORT", 8004, "/api/v1/health"),
    HealthCheck("simulateur", "SIMULATOR_PORT", 8005, "/api/v1/health"),
    HealthCheck("passerelle", "GATEWAY_PORT", 8000, "/health"),
    HealthCheck("frontend", "FRONTEND_PORT", 8080, "/"),
    HealthCheck("passerelle", "GATEWAY_PORT", 8000, "/api/v1/health", "route vers traitement"),
    HealthCheck("frontend", "FRONTEND_PORT", 8080, "/api/v1/health", "proxy vers la passerelle"),
)


def published_port(check: HealthCheck, env_values: dict[str, str]) -> int:
    """Port publié : variable d'environnement du shell, sinon .env, sinon valeur par défaut."""
    return int(os.environ.get(check.port_variable) or env_values.get(check.port_variable) or check.default_port)


def probe(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """GET sur `url` : (succès, détail). Un corps JSON doit avoir `status` égal à « ok »."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 : 127.0.0.1 seulement
            body = response.read().decode("utf-8", errors="replace")
            if response.status != 200:
                return False, f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code}"
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        return False, f"injoignable ({getattr(error, 'reason', error)})"
    try:
        data = json.loads(body)
    except ValueError:
        return True, "HTTP 200"  # page HTML du front-end
    if isinstance(data, dict) and data.get("status") != "ok":
        return False, f"statut {data.get('status')!r}"
    revision = data.get("revision") if isinstance(data, dict) else None
    return True, f"ok (révision {revision})" if revision else "ok"


def check_health(wait_seconds: int = 0) -> tuple[list[str], int]:
    """Interroge chaque /health (nouvelles tentatives pendant `wait_seconds`) ; rend les lignes et le nombre d'échecs."""
    env_values = parse_env(ENV_FILE.read_text(encoding="utf-8")) if ENV_FILE.exists() else {}
    deadline = time.monotonic() + wait_seconds
    while True:
        rows, failures = [], 0
        for check in HEALTH_CHECKS:
            url = f"http://127.0.0.1:{published_port(check, env_values)}{check.path}"
            ok, detail = probe(url)
            failures += 0 if ok else 1
            what = f"{check.name} ({check.label})" if check.label else check.name
            rows.append(f"  [{'OK' if ok else 'KO'}] {what:<36} {url:<46} {detail}")
        if failures == 0 or time.monotonic() >= deadline:
            return rows, failures
        time.sleep(3)


def print_health(wait_seconds: int = 0) -> int:
    rows, failures = check_health(wait_seconds)
    print("\n".join(rows))
    if failures:
        print(f"{failures} sonde(s) en échec. Voir les journaux :  python scripts/dev/dev.py logs <service>")
        return 1
    print(f"Les {len(rows)} sondes répondent.")
    return 0


def cmd_up(_: argparse.Namespace) -> int:
    """Démarre tout (l'ordre vient de depends_on dans docker-compose.yml), puis interroge chaque /health."""
    code = run_compose_step("up", "--build", "-d", "--remove-orphans")
    if code != 0:
        return code
    code = print_health(HEALTH_WAIT_SECONDS)
    if code == 0:
        env_values = parse_env(ENV_FILE.read_text(encoding="utf-8")) if ENV_FILE.exists() else {}
        gateway = next(c for c in HEALTH_CHECKS if c.name == "passerelle")
        front = next(c for c in HEALTH_CHECKS if c.name == "frontend")
        print(f"Front-end : http://localhost:{published_port(front, env_values)}   ·   "
              f"API (passerelle) : http://localhost:{published_port(gateway, env_values)}/api/v1/")
    return code


def cmd_health(args: argparse.Namespace) -> int:
    require_env()
    return print_health(args.wait)


def cmd_down(_: argparse.Namespace) -> int:
    """Arrête et supprime les conteneurs et le réseau du projet. Les données (volumes) sont conservées."""
    code = run_compose_step("down", "--remove-orphans")
    if code == 0:
        print("Conteneurs supprimés ; les données sont conservées (les effacer : db-reset).")
    return code


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
              "par celles de la sauvegarde. Les services et le front-end sont arrêtés pendant l'opération.")
        if input("Taper « restaurer » pour confirmer : ").strip().lower() != "restaurer":
            print("Annulé.")
            return 1
    compose("stop", *APP_SERVICES, check=False)
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
        ("mongo", "administrateur : 7 collections",
         'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
         '--authenticationDatabase admin "$MONGO_DB" --eval '
         '"if (db.getCollectionNames().length < 7) throw new Error(\'collections manquantes\')"', True),
        ("mongo", "administrateur : index de durée de vie sur raw_events",
         'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
         '--authenticationDatabase admin "$MONGO_DB" --eval '
         '"if (!db.raw_events.getIndexes().some(i => i.expireAfterSeconds)) throw new Error(\'TTL absent\')"', True),
        ("mongo", "collecte lit raw_events", mongo_as("svc_collecte", "MONGO_PASSWORD_COLLECTE", "db.raw_events.findOne()"), True),
        ("mongo", "collecte ne lit PAS audit_logs", mongo_as("svc_collecte", "MONGO_PASSWORD_COLLECTE", "db.audit_logs.findOne()"), False),
        ("mongo", "traitement lit raw_events", mongo_as("svc_traitement", "MONGO_PASSWORD_TRAITEMENT", "db.raw_events.findOne()"), True),
        ("mongo", "traitement ne lit PAS model_runs", mongo_as("svc_traitement", "MONGO_PASSWORD_TRAITEMENT", "db.model_runs.findOne()"), False),
        ("mongo", "traitement lit ingestion_runs", mongo_as("svc_traitement", "MONGO_PASSWORD_TRAITEMENT", "db.ingestion_runs.findOne()"), True),
        ("mongo", "collecte ne lit PAS ingestion_runs", mongo_as("svc_collecte", "MONGO_PASSWORD_COLLECTE", "db.ingestion_runs.findOne()"), False),
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


# --------------------------------------------------------------------------- schéma app : migrations Alembic (BE-02)
APP_SERVICE_DIR = ROOT / "services" / "traitement"
APP_MIGRATION_PACKAGES = ("alembic", "sqlalchemy", "psycopg")


def app_database_url(env: dict[str, str]) -> str:
    """Adresse SQLAlchemy du compte `svc_app` (propriétaire du schéma `app`) ; le mot de passe est encodé pour l'adresse."""
    return postgres_url(env, "svc_app", "PG_PASSWORD_APP").replace("postgresql://", "postgresql+psycopg://", 1)


def run_app_service(command: list[str], packages: tuple[str, ...]) -> int:
    """Lance `python -m ...` depuis services/traitement avec l'adresse de la base du compte `svc_app` (jamais sur la ligne de commande)."""
    require_env()
    for package in packages:
        if importlib.util.find_spec(package) is None:
            raise DevError(f"{package} est absent. L'installer :  {Path(sys.executable).name} -m pip install -r services/traitement/requirements-dev.txt")
    environment = {**os.environ, "APP_DATABASE_URL": app_database_url(etl_environment()), "PYTHONUTF8": "1"}
    return subprocess.run([sys.executable, "-m", *command], cwd=APP_SERVICE_DIR, env=environment, check=False).returncode


def cmd_db_migrate_app(_: argparse.Namespace) -> int:
    """Applique les migrations Alembic du schéma `app` (utilisateurs) avec le compte `svc_app` (BE-02)."""
    return run_app_service(["alembic", "upgrade", "head"], APP_MIGRATION_PACKAGES)


def cmd_user_create(args: argparse.Namespace) -> int:
    """Crée un compte de l'API métier, par exemple le premier administrateur ; le mot de passe est saisi sans écho (BE-03)."""
    return run_app_service(["app.cli", "create-user", args.username, "--role", args.role], (*APP_MIGRATION_PACKAGES, "argon2", "pydantic"))


# --------------------------------------------------------------------------- indicateurs décisionnels (DAT-07)
KPI_VERIFICATION = ROOT / "data" / "dwh" / "sql" / "kpi" / "controle" / "verifier.sql"


def cmd_db_check_kpi(_: argparse.Namespace) -> int:
    """Insère un jeu fabriqué dans une transaction annulée et compare chaque indicateur à son recalcul sur les sources (DAT-07)."""
    require_env()
    script = KPI_VERIFICATION.read_text(encoding="utf-8")
    result = compose("exec", "-T", "postgres", "sh", "-c",
                     'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q', check=False, capture=True, input_text=script)
    print(result.stdout, end="")
    print(result.stderr.replace("psql:<stdin>", "verifier.sql"), end="", file=sys.stderr)
    return result.returncode


# --------------------------------------------------------------------------- événements dans MongoDB (LOC-02)
EVENT_TEST_SUFFIX = ":db-check"  # identifiant des documents d'essai : supprimés avant et après le contrôle
MONGO_ADMIN = ('mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
               '--authenticationDatabase admin "$MONGO_DB"')
MONGO_COLLECTE = 'mongosh --quiet -u svc_collecte -p "$MONGO_PASSWORD_COLLECTE" --authenticationDatabase "$MONGO_DB" "$MONGO_DB"'
VALIDATION_FAILED = 121  # code MongoDB « Document failed validation »


def raw_event_documents(event: dict, received_at: str) -> tuple[dict, dict]:
    """Deux documents pour `raw_events` en JSON étendu (les dates sont `{"$date": ...}`) : un conforme, un sans provenance.

    Le service de collecte ajoute `received_at` à l'écriture : il n'est pas dans l'événement publié sur le bus.
    """
    valid = {**event, "id": event["id"] + EVENT_TEST_SUFFIX, "time": {"$date": event["time"]},
             "received_at": {"$date": received_at}}
    without_provenance = {**valid, "id": valid["id"] + "-sans-provenance",
                          "data": {k: v for k, v in event["data"].items() if k != "provenance"}}
    return valid, without_provenance


def insert_script(document: dict) -> str:
    """Script mongosh : insère le document et affiche une ligne JSON {accepted, code} (jamais d'exception brute)."""
    return ("try { const r = db.raw_events.insertOne(EJSON.deserialize(" + json.dumps(document) + ")); "
            "print(JSON.stringify({accepted: r.acknowledged})); } "
            "catch (e) { print(JSON.stringify({accepted: false, code: e.code, name: e.codeName || e.name})); }\n")


def parse_result_line(output: str) -> dict | None:
    """Dernier objet JSON de la sortie ; None s'il n'y en a pas.

    mongosh lit son script sur l'entrée standard et préfixe chaque réponse de son invite (`novaria> {...}`).
    """
    for line in reversed(output.splitlines()):
        start, end = line.find("{"), line.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(line[start:end + 1])
            except ValueError:
                return None
    return None


def run_mongosh(login: str, script: str) -> subprocess.CompletedProcess:
    return compose("exec", "-T", "mongo", "sh", "-c", login, check=False, capture=True, input_text=script)


def cmd_db_check_events(args: argparse.Namespace) -> int:
    """Insère une mesure conforme (acceptée) puis la même sans provenance (refusée) avec le compte de collecte (LOC-02)."""
    require_env()
    try:
        event = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DevError(f"Événement illisible ({args.file}) : {error}") from error
    received_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    valid, without_provenance = raw_event_documents(event, received_at)
    ids = json.dumps([valid["id"], without_provenance["id"]])
    cleanup = f"db.raw_events.deleteMany({{id: {{$in: {ids}}}}})\n"
    ttl = ("const i = db.raw_events.getIndexes().find((x) => x.expireAfterSeconds !== undefined); "
           "print(JSON.stringify({ttl: i && i.expireAfterSeconds, "
           "expected: Number(process.env.RAW_EVENTS_TTL_SECONDS || 1209600)}))\n")
    failures = 0

    def report(ok: bool, label: str) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  [{'OK' if ok else 'KO'}] mongo    {label}")

    run_mongosh(MONGO_ADMIN, cleanup)
    try:
        accepted = run_mongosh(MONGO_COLLECTE, insert_script(valid))
        result = parse_result_line(accepted.stdout)
        report(accepted.returncode == 0 and result == {"accepted": True}, "collecte : mesure conforme acceptée")
        refused = run_mongosh(MONGO_COLLECTE, insert_script(without_provenance))
        result = parse_result_line(refused.stdout)
        report(refused.returncode == 0 and result is not None and result.get("accepted") is False
               and result.get("code") == VALIDATION_FAILED, "collecte : mesure sans provenance refusée (validateur)")
        index = run_mongosh(MONGO_ADMIN, ttl)
        result = parse_result_line(index.stdout) or {}
        days = (result.get("ttl") or 0) / 86400
        report(index.returncode == 0 and bool(result.get("ttl")) and result.get("ttl") == result.get("expected"),
               f"raw_events : index de durée de vie de {days:g} jours")
    finally:
        run_mongosh(MONGO_ADMIN, cleanup)
    print("Toutes les vérifications passent." if failures == 0 else f"{failures} vérification(s) en échec.")
    return 0 if failures == 0 else 1


# --------------------------------------------------------------------------- ETL (DAT-03)
ETL_DIR = ROOT / "data" / "etl"
ETL_REQUIREMENTS = "data/etl/requirements.txt"
REPLAY_REPORT = ROOT / "docs" / "03-donnees" / "rapport-rejeu-etl.md"  # emplacement fixe du rapport de comparaison


def mongo_url(env: dict[str, str], user: str, password_variable: str) -> str:
    """Adresse MongoDB du poste pour un compte de service ; le mot de passe est encodé pour l'adresse."""
    missing = [name for name in (password_variable, "MONGO_DB") if not env.get(name)]
    if missing:
        raise DevError(f"Variable absente de .env : {', '.join(missing)} (init-env --force puis db-reset).")
    database = env["MONGO_DB"]
    password = urllib.parse.quote(env[password_variable], safe="")
    port = env.get("MONGO_PORT") or "27017"
    return f"mongodb://{user}:{password}@127.0.0.1:{port}/{database}?authSource={database}"


def postgres_url(env: dict[str, str], user: str, password_variable: str) -> str:
    """Adresse PostgreSQL du poste pour un compte de service ; le mot de passe est encodé pour l'adresse."""
    missing = [name for name in (password_variable, "POSTGRES_DB") if not env.get(name)]
    if missing:
        raise DevError(f"Variable absente de .env : {', '.join(missing)} (init-env --force puis db-reset).")
    password = urllib.parse.quote(env[password_variable], safe="")
    return f"postgresql://{user}:{password}@127.0.0.1:{env.get('POSTGRES_PORT') or '5432'}/{env['POSTGRES_DB']}"


def etl_environment() -> dict[str, str]:
    """Variables de .env, recouvertes par celles du shell comme le fait Docker Compose (projet jetable, autre port)."""
    env = parse_env(ENV_FILE.read_text(encoding="utf-8"))
    env.update({name: os.environ[name] for name in env if name in os.environ})
    return env


def run_etl(module: str, options: list[str], drivers: tuple[str, ...], extra: dict[str, str]) -> int:
    """Lance un pipeline de data/etl depuis son dossier. L'adresse des bases (donc les mots de passe) passe par
    l'environnement du processus, pas par sa ligne de commande."""
    return run_etl_process(module, options, drivers, extra).returncode


def run_etl_process(module: str, options: list[str], drivers: tuple[str, ...], extra: dict[str, str], *, capture: bool = False) -> subprocess.CompletedProcess:
    """Comme `run_etl`, en rendant le processus ; avec `capture`, sa sortie standard est lue (UTF-8) au lieu d'aller au terminal."""
    require_env()
    for driver in drivers:
        if importlib.util.find_spec(driver) is None:
            raise DevError(f"{driver} est absent. L'installer :  {Path(sys.executable).name} -m pip install -r {ETL_REQUIREMENTS}")
    environment = {**os.environ, **extra, "PYTHONUTF8": "1"}
    sortie = {"stdout": subprocess.PIPE, "text": True, "encoding": "utf-8"} if capture else {}
    return subprocess.run([sys.executable, "-m", module, *options], cwd=ETL_DIR, env=environment, check=False, **sortie)


def window_options(args: argparse.Namespace, names: tuple[str, ...]) -> list[str]:
    return [item for name in names if getattr(args, name) for item in (f"--{name.replace('_', '-')}", str(getattr(args, name)))]


def cmd_etl_paris(args: argparse.Namespace) -> int:
    """Ingère une fenêtre du comptage routier de Paris : fichier brut dans data/datasets/, entrée dans MongoDB (DAT-03)."""
    require_env()
    env = etl_environment()
    url = mongo_url(env, "svc_traitement", "MONGO_PASSWORD_TRAITEMENT")
    return run_etl("pipelines.ingerer_paris", window_options(args, ("day", "start", "end")), ("pymongo",), {"MONGO_URL": url})


def cmd_etl_nettoyer_paris(args: argparse.Namespace) -> int:
    """Nettoie un fichier brut de Paris : lignes propres, rejets dans dwh.etl_reject, taux de rejet dans MongoDB (DAT-04)."""
    require_env()
    env = etl_environment()
    extra = {"MONGO_URL": mongo_url(env, "svc_traitement", "MONGO_PASSWORD_TRAITEMENT"),
             "POSTGRES_URL": postgres_url(env, "svc_traitement", "PG_PASSWORD_TRAITEMENT")}
    if args.file and args.file.parent != Path("."):
        # Le pipeline s'exécute depuis data/etl : un chemin relatif au dépôt n'y mènerait nulle part. Un nom seul reste un nom
        # (le pipeline le cherche dans le dossier des fichiers bruts) ; un chemin doit mener à ce dossier, sinon il est refusé.
        args.file = args.file.resolve()
    options = window_options(args, ("day", "file", "alert_threshold"))
    return run_etl("pipelines.nettoyer_paris", options, ("pymongo", "psycopg"), extra)


def etl_database_urls() -> dict[str, str]:
    env = etl_environment()
    return {"MONGO_URL": mongo_url(env, "svc_traitement", "MONGO_PASSWORD_TRAITEMENT"),
            "POSTGRES_URL": postgres_url(env, "svc_traitement", "PG_PASSWORD_TRAITEMENT")}


def etl_file_argument(path: Path) -> str:
    """Un nom seul reste un nom (le pipeline le cherche dans son dossier) ; un chemin devient absolu, car le pipeline part de data/etl."""
    return str(path.resolve()) if path.parent != Path(".") else str(path)


def cmd_etl_lot(args: argparse.Namespace) -> int:
    """Lot planifié : ingestion et nettoyage de Paris, puis chargement de fenêtres si demandé (DAT-06). Commande du cron et de la tâche Windows."""
    require_env()
    windows = etl_file_argument(args.windows) if args.windows else None
    options = [item for flag, value in (("--day", args.day), ("--windows", windows), ("--run-id", args.run_id)) if value for item in (flag, str(value))]
    return run_etl("pipelines.lot", options, ("pymongo", "psycopg"), etl_database_urls())


def cmd_etl_load(args: argparse.Namespace) -> int:
    """Charge un fichier de fenêtres dans dwh.fact_traffic_window ; rejouable sans changer les totaux (DAT-06)."""
    require_env()
    return run_etl("pipelines.charger_entrepot", ["--file", etl_file_argument(args.file), "--run-id", args.run_id], ("psycopg",), etl_database_urls())


def cmd_etl_replay(args: argparse.Namespace) -> int:
    """Charge un fichier de fenêtres trois fois (initial, rejeu, reprise) et écrit le rapport de comparaison des totaux (DAT-06)."""
    require_env()
    options = ["--file", etl_file_argument(args.file), "--run-id", args.run_id]
    if args.from_scratch:
        options.append("--from-scratch")
    done = run_etl_process("pipelines.rejouer", options, ("psycopg",), etl_database_urls(), capture=args.report)
    if args.report:
        print(done.stdout, end="")
        if done.returncode in (0, 2):  # rapport rendu : totaux identiques (0) ou différents (2), à lire dans les deux cas
            REPLAY_REPORT.write_text(done.stdout, encoding="utf-8", newline="\n")
    return done.returncode


def cmd_etl_package(args: argparse.Namespace) -> int:
    """Empaquette la logique ETL en une archive reproductible (dist/novaria-etl-<version>.zip), la forme d'un job AWS Glue (DAT-06)."""
    return subprocess.run([sys.executable, str(ETL_DIR / "pipelines" / "empaqueter.py")], cwd=ROOT, check=False).returncode


# --------------------------------------------------------------------------- Kafka (ADR-009, LOC-04)
# Les outils en ligne de commande de Kafka sont dans le conteneur : aucun client Kafka à installer sur le poste.
KAFKA_BIN = "/opt/kafka/bin"
KAFKA_BOOTSTRAP = "localhost:9092"  # adresse vue depuis le conteneur du broker
KAFKA_PARTITIONS = 3  # ADR-009 §4.3 : 3 partitions par sujet en local
KAFKA_SEPARATOR = "|"  # sépare partition, décalage, clé et valeur à la relecture, clé et valeur à la publication
EXAMPLE_MEASUREMENT = ROOT / "contracts" / "events" / "examples" / "mesure-valide.json"
VALIDATOR = ROOT / "contracts" / "validate_events.py"
TOPICS_FILE = ROOT / "contracts" / "topics.json"  # matrice des sujets : type d'événement, schéma, producteurs, consommateurs


class Topic(NamedTuple):
    name: str
    key: str  # champ qui sert de clé de partition (même clé : même partition, donc ordre conservé)
    configs: tuple[str, ...] = ()


# Sujets du bus (ADR-009 §4.1). La clé est celle des contrats : `subject` de l'enveloppe = `data.intersection_id`.
KAFKA_TOPICS: tuple[Topic, ...] = (
    Topic("iot.raw", "intersection_id", ("retention.ms=604800000",)),  # rétention de 7 jours (ADR-009 §4.3)
    Topic("traffic.indicators", "intersection_id"),
    Topic("traffic.recommendations", "intersection_id"),
    Topic("alerts.events", "intersection_id"),
    Topic("signal.status", "intersection_id"),
    Topic("errors.dlq", "intersection_id"),
)


def kafka_tool(tool: str, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    """Lance un outil Kafka dans le conteneur `kafka` ; la sortie est capturée."""
    return compose("exec", "-T", "kafka", f"{KAFKA_BIN}/{tool}", "--bootstrap-server", KAFKA_BOOTSTRAP, *args,
                   check=False, capture=True, input_text=input_text)


def parse_topic_descriptions(output: str) -> dict[str, tuple[int, int, dict[str, str]]]:
    """Lit la sortie de `kafka-topics.sh --describe` : {sujet: (partitions, réplication, configuration)}."""
    topics = {}
    pattern = re.compile(r"^Topic: (\S+)\s+TopicId: \S+\s+PartitionCount: (\d+)\s+ReplicationFactor: (\d+)\s+Configs: (.*)$")
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match:
            configs = dict(item.split("=", 1) for item in match.group(4).split(",") if "=" in item)
            topics[match.group(1)] = (int(match.group(2)), int(match.group(3)), configs)
    return topics


def parse_offsets(output: str, topic: str) -> dict[int, int]:
    """Lit la sortie de `kafka-get-offsets.sh` (lignes « sujet:partition:décalage »)."""
    offsets = {}
    for line in output.splitlines():
        name, _, rest = line.strip().rpartition(":")  # décalage
        head, _, partition = name.rpartition(":")
        if head == topic and partition.isdigit() and rest.isdigit():
            offsets[int(partition)] = int(rest)
    return offsets


def parse_consumed(output: str) -> tuple[int, int, str, str] | None:
    """Lit la première ligne « Partition:p|Offset:o|clé|valeur » d'un consommateur ; None si absente."""
    for line in output.splitlines():
        if line.startswith("Partition:"):
            head = line.split(KAFKA_SEPARATOR, 3)
            if len(head) == 4 and head[1].startswith("Offset:"):
                return int(head[0].removeprefix("Partition:")), int(head[1].removeprefix("Offset:")), head[2], head[3]
    return None


def cmd_kafka_up(_: argparse.Namespace) -> int:
    code = run_compose_step("up", "-d", "--wait", "kafka")
    if code == 0:
        print("Kafka prêt : 127.0.0.1:9094 depuis le poste (KAFKA_PORT), kafka:9092 depuis les conteneurs.")
    return code


def kafka_topic_rows() -> tuple[list[str], int]:
    """Crée les sujets manquants, puis rend les lignes du tableau et le nombre d'anomalies."""
    listing = kafka_tool("kafka-topics.sh", "--list")
    if listing.returncode != 0:
        raise DevError("Impossible de lister les sujets :\n" + (listing.stderr or listing.stdout).strip())
    existing = set(listing.stdout.split())
    created = set()
    for topic in KAFKA_TOPICS:
        if topic.name in existing:
            continue
        configs = [arg for config in topic.configs for arg in ("--config", config)]
        result = kafka_tool("kafka-topics.sh", "--create", "--topic", topic.name, "--partitions",
                            str(KAFKA_PARTITIONS), "--replication-factor", "1", *configs)
        if result.returncode != 0:
            raise DevError(f"Création de {topic.name} impossible :\n" + (result.stderr or result.stdout).strip())
        created.add(topic.name)
    description = kafka_tool("kafka-topics.sh", "--describe")
    if description.returncode != 0:
        raise DevError("Impossible de décrire les sujets :\n" + (description.stderr or description.stdout).strip())
    found = parse_topic_descriptions(description.stdout)
    rows = [f"  {'sujet':<24} {'partitions':<11} {'clé de partition':<17} état"]
    failures = 0
    for topic in KAFKA_TOPICS:
        if topic.name not in found:
            failures += 1
            rows.append(f"  {topic.name:<24} {'-':<11} {topic.key:<17} [KO] absent")
            continue
        partitions, _, configs = found[topic.name]
        wrong = [f"{k} attendu {v}" for k, v in (c.split("=", 1) for c in topic.configs) if configs.get(k) != v]
        if partitions != KAFKA_PARTITIONS:
            wrong.append(f"{KAFKA_PARTITIONS} partitions attendues")
        failures += 1 if wrong else 0
        state = f"[KO] {', '.join(wrong)}" if wrong else f"[OK] {'créé' if topic.name in created else 'déjà présent'}"
        rows.append(f"  {topic.name:<24} {partitions:<11} {topic.key:<17} {state}")
    return rows, failures


def cmd_kafka_topics(_: argparse.Namespace) -> int:
    """Démarre Kafka si besoin, crée les 6 sujets manquants (sans toucher aux existants) et les vérifie."""
    code = run_compose_step("up", "-d", "--wait", "kafka")
    if code != 0:
        return code
    rows, failures = kafka_topic_rows()
    print("\n".join(rows))
    print(f"{len(KAFKA_TOPICS)} sujets présents et conformes." if failures == 0
          else f"{failures} sujet(s) en échec.")
    return 0 if failures == 0 else 1


def cmd_kafka_roundtrip(args: argparse.Namespace) -> int:
    """Publie un événement, le relit au décalage exact où il a été écrit, puis le valide contre le contrat."""
    require_env()
    if importlib.util.find_spec("jsonschema") is None or importlib.util.find_spec("referencing") is None:
        raise DevError("Le validateur de contrats demande : pip install jsonschema referencing")
    try:
        event = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DevError(f"Événement illisible ({args.file}) : {error}") from error
    if not isinstance(event, dict) or not event.get("subject"):
        raise DevError("L'événement doit être un objet avec un champ `subject` (la clé de partition).")
    key = str(event["subject"])
    expected_type = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))["topics"].get(args.topic, {}).get("type")
    if expected_type is not None and event.get("type") != expected_type:
        raise DevError(f"Le sujet {args.topic} reçoit des événements {expected_type}, pas {event.get('type')!r} "
                       "(matrice des sujets : contracts/topics.json).")
    described = kafka_tool("kafka-topics.sh", "--describe", "--topic", args.topic)
    if described.returncode != 0 or args.topic not in parse_topic_descriptions(described.stdout):
        raise DevError(f"Le sujet {args.topic} n'existe pas. Le créer :  python scripts/dev/dev.py kafka-topics")

    before = parse_offsets(kafka_tool("kafka-get-offsets.sh", "--topic", args.topic, "--time", "-1").stdout, args.topic)
    sent = json.dumps(event, separators=(",", ":"))
    produced = kafka_tool(
        "kafka-console-producer.sh", "--topic", args.topic, "--reader-property", "parse.key=true",
        "--reader-property", f"key.separator={KAFKA_SEPARATOR}", input_text=f"{key}{KAFKA_SEPARATOR}{sent}\n")
    after = parse_offsets(kafka_tool("kafka-get-offsets.sh", "--topic", args.topic, "--time", "-1").stdout, args.topic)
    grown = [p for p, end in after.items() if end > before.get(p, 0)]
    if produced.returncode != 0 or len(grown) != 1 or after[grown[0]] != before.get(grown[0], 0) + 1:
        raise DevError("Publication non confirmée (un seul message devait apparaître) :\n"
                       + (produced.stderr or produced.stdout).strip())
    partition, offset = grown[0], before.get(grown[0], 0)
    print(f"  [OK] publié  : sujet {args.topic}, partition {partition}, décalage {offset}, clé {key}")

    read = kafka_tool(
        "kafka-console-consumer.sh", "--topic", args.topic, "--partition", str(partition), "--offset", str(offset),
        "--max-messages", "1", "--timeout-ms", "15000", "--formatter-property", "print.partition=true",
        "--formatter-property", "print.offset=true", "--formatter-property", "print.key=true",
        "--formatter-property", f"key.separator={KAFKA_SEPARATOR}")
    consumed = parse_consumed(read.stdout)
    if consumed is None:
        raise DevError("Relecture impossible :\n" + (read.stderr or read.stdout).strip())
    _, _, read_key, read_value = consumed
    if read_key != key or json.loads(read_value) != event:
        print("  [KO] relu    : le message relu diffère du message publié")
        return 1
    print(f"  [OK] relu    : partition {partition}, décalage {offset}, clé {read_key}, contenu identique à {args.file.name}")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"relu-{args.topic}-p{partition}-o{offset}.json"
        target.write_text(read_value, encoding="utf-8")
        checked = subprocess.run([sys.executable, str(VALIDATOR), str(target)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", check=False)
    for line in (checked.stdout + checked.stderr).splitlines():
        print(f"  [contrat] {line}")
    if checked.returncode != 0:
        return 1
    print("  [OK] conforme au contrat (schéma et règles entre champs)")
    return 0


# --------------------------------------------------------------------------- dépendances verrouillées (MS-06)
# Chaque service écrit ses dépendances en intervalles dans requirements.in et requirements-dev.in ; les fichiers
# requirements.txt et requirements-dev.txt sont le verrou : versions exactes et empreintes de tous les fichiers de
# chaque version, pour tous les systèmes (--universal). Les images s'installent avec --require-hashes --only-binary.
UV_VERSION = "0.13.6"  # version de l'outil de résolution : fixée pour que deux postes produisent le même verrou
LOCK_IMAGE = "python:3.12-slim"  # Python minimal du projet (requires-python)
LOCK_PAIRS = (("requirements.in", "requirements.txt"), ("requirements-dev.in", "requirements-dev.txt"))


def lockable_services(name: str | None = None) -> list[Path]:
    """Dossiers de services/ qui ont un requirements.in (le gabarit compris), ou celui qui porte le nom `name`."""
    directories = sorted(p for p in (ROOT / "services").iterdir() if (p / "requirements.in").is_file())
    if name is not None:
        directories = [d for d in directories if d.name == name]
        if not directories:
            raise DevError(f"Aucun service « {name} » avec un requirements.in dans services/.")
    return directories


def lock_command(directory: Path) -> list[str]:
    """Commande `docker run` qui recalcule les deux verrous d'un service (aucun outil à installer sur le poste)."""
    compile_steps = " && ".join(
        f"uv pip compile --quiet {source} --universal --generate-hashes --python-version 3.12 -o {target}"
        for source, target in LOCK_PAIRS
    )
    user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []  # fichiers au nom de la personne
    return ["docker", "run", "--rm", *user, "-e", "HOME=/tmp", "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1", "-e", "PATH=/tmp/.local/bin:/usr/local/bin:/usr/bin:/bin",
            "-v", f"{directory}:/work", "-w", "/work", LOCK_IMAGE, "sh", "-c",
            f"pip install --quiet --user uv=={UV_VERSION} && {compile_steps}"]


def cmd_lock_deps(args: argparse.Namespace) -> int:
    """Recalcule requirements.txt et requirements-dev.txt depuis les fichiers .in (réseau nécessaire)."""
    require_docker()
    for directory in lockable_services(args.service):
        print(f"Verrou de {directory.name} …")
        code = subprocess.run(lock_command(directory), check=False).returncode
        if code != 0:
            print(f"ERREUR : le verrou de {directory.name} a échoué (code {code}).", file=sys.stderr)
            return code
    print("Verrous à jour. Relire le diff, lancer les tests du service, puis commiter .in et .txt ensemble.")
    return 0


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


def cmd_new_service(args: argparse.Namespace) -> int:
    """Crée services/<nom> depuis le gabarit (MS-04) ; la logique est dans new_service.py."""
    import new_service

    try:
        target = new_service.create(args.name, ROOT)
    except new_service.NewServiceError as error:
        raise DevError(str(error)) from error
    print(f"Service créé : {target.relative_to(ROOT).as_posix()}")
    print("Suite : voir CONTRIBUTING.md, « Créer un nouveau service ». La CI n'est pas à modifier.")
    return 0


# --------------------------------------------------------------------------- tableau de bord en local (FE-04)
FRONTEND_DIR = ROOT / "frontend"
API_PORT = 8000  # cible du proxy de Vite (frontend/vite.config.ts)
API_PACKAGES = ("fastapi", "uvicorn", "sqlalchemy", "psycopg", "argon2", "pydantic")
API_REQUIREMENTS = ("services/traitement/requirements.txt", "data/etl/requirements.txt")


def cmd_dev_deps(_: argparse.Namespace) -> int:
    """Installe dans l'interpréteur courant les paquets de l'API de traitement et des commandes ETL (un venv, de préférence)."""
    for requirements in API_REQUIREMENTS:  # deux passes : l'un des fichiers a des empreintes (--require-hashes), pas l'autre
        code = subprocess.run([sys.executable, "-m", "pip", "install", "-r", requirements], cwd=ROOT, check=False).returncode
        if code:
            return code
    return 0


def api_environment(env: dict[str, str]) -> dict[str, str]:
    """Variables de l'API de traitement sur le poste : les mêmes que Compose, avec l'adresse 127.0.0.1 des bases (jamais affichées)."""
    if not env.get("JWT_SECRET"):
        raise DevError("JWT_SECRET est vide dans .env (init-env --force puis db-reset).")
    return {
        **os.environ,
        "POSTGRES_URL": postgres_url(env, "svc_traitement", "PG_PASSWORD_TRAITEMENT").replace("postgresql://", "postgresql+psycopg://", 1),
        "APP_DATABASE_URL": app_database_url(env),
        "JWT_SECRET": env["JWT_SECRET"],
        "SERVICE_NAME": "traitement",
        "ENVIRONMENT": "local",
        "PYTHONUTF8": "1",
    }


def cmd_api_run(_: argparse.Namespace) -> int:
    """Lance l'API de traitement (authentification et indicateurs) sur http://127.0.0.1:8000, avec les bases du poste."""
    require_env()
    for package in API_PACKAGES:
        if importlib.util.find_spec(package) is None:
            raise DevError(f"{package} est absent. L'installer :  {Path(sys.executable).name} scripts/dev/dev.py dev-deps")
    environment = api_environment(etl_environment())
    print(f"API de traitement : http://127.0.0.1:{API_PORT}/docs  (Ctrl+C pour arrêter ; bases : db-up)")
    command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(API_PORT)]
    try:
        return subprocess.run(command, cwd=APP_SERVICE_DIR, env=environment, check=False).returncode
    except KeyboardInterrupt:
        return 0


def cmd_front_dev(_: argparse.Namespace) -> int:
    """Lance le front-end (Vite, http://localhost:5173) ; installe les dépendances npm la première fois."""
    npm = shutil.which("npm")
    if npm is None:
        raise DevError("npm est absent (Node.js 22 ou plus). Voir docs/08-exploitation/poste-de-travail.md.")
    if not (FRONTEND_DIR / "node_modules").is_dir():
        code = subprocess.run([npm, "ci"], cwd=FRONTEND_DIR, check=False).returncode
        if code:
            return code
    print(f"Front-end : http://localhost:5173  (Ctrl+C pour arrêter ; l'API doit tourner : api-run, sur le port {API_PORT})")
    try:
        return subprocess.run([npm, "run", "dev"], cwd=FRONTEND_DIR, check=False).returncode
    except KeyboardInterrupt:
        return 0


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
    add("up", cmd_up, "démarre tout (bases, bus, 4 services, simulateur, passerelle, front-end) et vérifie chaque /health")
    add("down", cmd_down, "arrête et supprime les conteneurs (les données sont conservées)")
    lock = add("lock-deps", cmd_lock_deps, "recalcule les verrous de dépendances (requirements*.txt) depuis les .in")
    lock.add_argument("service", nargs="?", help="un seul service (tous par défaut)")
    health = add("health", cmd_health, "interroge le /health de chaque conteneur")
    health.add_argument("--wait", type=int, default=0, metavar="SECONDES", help="réessaie pendant ce délai (0 : un seul essai)")
    add("db-up", cmd_db_up, "démarre PostgreSQL et MongoDB, puis applique les migrations")
    add("db-migrate", cmd_db_migrate, "applique les migrations SQL en attente")
    add("db-migrate-app", cmd_db_migrate_app, "applique les migrations Alembic du schéma app (compte svc_app)")
    user = add("user-create", cmd_user_create, "crée un compte de l'API (premier administrateur) ; mot de passe saisi sans écho")
    user.add_argument("username", help="3 à 64 caractères parmi a-z, 0-9, _ . -")
    user.add_argument("--role", required=True, choices=["viewer", "operator", "admin"], help="droit d'accès")
    add("dev-deps", cmd_dev_deps, "installe les paquets Python de l'API de traitement et de l'ETL dans l'interpréteur courant")
    add("api-run", cmd_api_run, "lance l'API de traitement sur http://127.0.0.1:8000 (tableau de bord en local)")
    add("front-dev", cmd_front_dev, "lance le front-end (Vite) sur http://localhost:5173")
    add("db-status", cmd_db_status, "état des bases et des migrations")
    add("db-check", cmd_db_check, "vérifie rôles, droits, collections et index")
    events = add("db-check-events", cmd_db_check_events, "insère une mesure conforme (acceptée) et une sans provenance (refusée)")
    events.add_argument("--file", type=Path, default=EXAMPLE_MEASUREMENT, help="événement de départ (mesure-valide.json)")
    etl = add("etl-paris", cmd_etl_paris, "ingère une fenêtre du comptage routier de Paris : fichier brut + journal MongoDB")
    etl.add_argument("--day", metavar="AAAA-MM-JJ", help="un jour entier en UTC")
    etl.add_argument("--start", metavar="INSTANT", help="début inclus avec fuseau (2026-10-18T10:00:00Z), avec --end")
    etl.add_argument("--end", metavar="INSTANT", help="fin exclue avec fuseau")
    clean = add("etl-nettoyer-paris", cmd_etl_nettoyer_paris, "nettoie un fichier brut de Paris : propres, rejets (dwh.etl_reject), taux de rejet (MongoDB)")
    clean.add_argument("--day", metavar="AAAA-MM-JJ", help="le fichier brut du jour entier (ingéré par etl-paris --day)")
    clean.add_argument("--file", type=Path, help="un fichier brut précis")
    clean.add_argument("--alert-threshold", metavar="TAUX", help="taux de rejet au-delà duquel alerter, de 0 à 1 (0.5)")
    lot = add("etl-lot", cmd_etl_lot, "lot ETL planifié : ingestion et nettoyage de Paris, chargement de fenêtres (cron, Planificateur de tâches)")
    lot.add_argument("--day", metavar="AAAA-MM-JJ", help="jour UTC à traiter (la veille par défaut)")
    lot.add_argument("--windows", type=Path, metavar="FICHIER", help="fichier CSV de fenêtres à charger dans l'entrepôt, avec --run-id")
    lot.add_argument("--run-id", help="identifiant du run des fenêtres")
    load = add("etl-charger", cmd_etl_load, "charge un fichier de fenêtres dans dwh.fact_traffic_window (idempotent)")
    load.add_argument("--file", type=Path, required=True, help="fichier CSV de fenêtres")
    load.add_argument("--run-id", required=True, help="identifiant du run (partie de la clé d'idempotence)")
    replay = add("etl-rejouer", cmd_etl_replay, "charge trois fois le même fichier et compare les totaux (rapport de comparaison)")
    replay.add_argument("--file", type=Path, required=True, help="fichier CSV de fenêtres")
    replay.add_argument("--run-id", required=True, help="identifiant du run : seules ses lignes sont touchées")
    replay.add_argument("--from-scratch", action="store_true", help="supprime d'abord les lignes de ce run")
    replay.add_argument("--report", action="store_true", help="enregistre aussi le rapport dans docs/03-donnees/rapport-rejeu-etl.md")
    package = add("etl-package", cmd_etl_package, "empaquette la logique ETL en dist/novaria-etl-<version>.zip (reproductible)")
    add("db-check-kpi", cmd_db_check_kpi, "recalcule les 5 indicateurs sur un jeu fabriqué (transaction annulée) et les compare aux vues")
    add("kafka-up", cmd_kafka_up, "démarre Kafka (mode KRaft) et attend qu'il soit prêt")
    add("kafka-topics", cmd_kafka_topics, "crée les 6 sujets du bus s'ils manquent et les vérifie")
    trip = add("kafka-roundtrip", cmd_kafka_roundtrip, "publie un événement, le relit et le valide contre le contrat")
    trip.add_argument("--file", type=Path, default=EXAMPLE_MEASUREMENT, help="événement à publier (mesure-valide.json)")
    trip.add_argument("--topic", default="iot.raw", help="sujet de publication (iot.raw)")
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
    add("new-service", cmd_new_service, "crée services/<nom> depuis le gabarit").add_argument(
        "name", help="nom du service : minuscules, chiffres, tirets (exemple : alerte)")
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
