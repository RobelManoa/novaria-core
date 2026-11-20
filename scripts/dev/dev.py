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
import socket
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
REPORTS_DIR = ROOT / "var" / "reports"  # dépôt du robot (IA-07), monté en lecture seule dans le traitement
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
    # Sans ce dossier, Docker créerait le point de montage au nom de root : le robot ne pourrait plus y écrire.
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
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


# --------------------------------------------------------------------------- jeu d'entraînement v1 (IA-08)
DATASET_BUILDER = ROOT / "ml" / "src" / "construire_jeu.py"


def cmd_dataset_build(args: argparse.Namespace) -> int:
    """Construit le jeu d'entraînement v1 (runs du simulateur, vérité terrain, Parquet, fiche de provenance) : environ 40 s, bibliothèque standard."""
    command = [sys.executable, str(DATASET_BUILDER)]
    if args.sortie:
        command += ["--sortie", str(args.sortie)]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


# --------------------------------------------------------------------------- règle de référence (IA-01)
REFERENCE_MESURE = ROOT / "ml" / "src" / "mesurer_reference.py"


def cmd_reference_mesure(args: argparse.Namespace) -> int:
    """Mesure la règle de seuils de l'ADR-028 sur l'entraînement et la validation du jeu v1 (le test n'est pas lisible)."""
    command = [sys.executable, str(REFERENCE_MESURE)]
    if args.sensibilite:
        command.append("--sensibilite")
    if args.json:
        command.append("--json")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


# --------------------------------------------------------------------------- variables et découpage (IA-02)
PREPARATION_CHECK = ROOT / "ml" / "src" / "preparer_variables.py"


def cmd_preparation_check(args: argparse.Namespace) -> int:
    """Vérifie le découpage (par run et par scénario) et les variables (permises, sans fuite) du jeu v1 ; le test n'est pas lu."""
    command = [sys.executable, str(PREPARATION_CHECK)]
    if args.json:
        command.append("--json")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


# --------------------------------------------------------------------------- entraînement et comparaison (IA-03)
ML_REQUIREMENTS = ROOT / "ml" / "requirements.txt"
ML_VENV = ROOT / "ml" / ".venv"
ML_TRAIN = ROOT / "ml" / "src" / "entrainer.py"
ML_ETAPES = ("validation", "test", "rapport")


def ml_python() -> Path:
    """L'interpréteur de l'environnement de l'entraînement (ml/.venv) : `Scripts/python.exe` sous Windows, `bin/python` ailleurs."""
    return ML_VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def cmd_ml_env(_: argparse.Namespace) -> int:
    """Crée ml/.venv et y installe scikit-learn depuis ml/requirements.txt, **en exigeant les empreintes** (--require-hashes)."""
    if not ml_python().exists():
        code = subprocess.run([sys.executable, "-m", "venv", str(ML_VENV)], cwd=ROOT, check=False).returncode
        if code:
            return code
    return subprocess.run([str(ml_python()), "-m", "pip", "install", "--require-hashes", "-r", str(ML_REQUIREMENTS)], cwd=ROOT, check=False).returncode


def cmd_ml_train(args: argparse.Namespace) -> int:
    """Étape de l'IA-03 : validation (réglage, choix), test (une seule lecture) ou rapport (tableaux)."""
    if not ml_python().exists():
        print("ml/.venv est absent : lancer d'abord « ml-env » (scikit-learn y est installé avec ses empreintes).", file=sys.stderr)
        return 2
    return subprocess.run([str(ml_python()), str(ML_TRAIN), args.etape], cwd=ROOT, check=False).returncode


ML_ANOMALIES = ROOT / "ml" / "src" / "detecter_anomalies.py"
ML_SUMO = ROOT / "ml" / "src" / "lancer_sumo.py"
ML_SUMO_ETAPES = ("image", "calibrer", "simuler", "rejouer", "comparer")
ML_PREVISION = ROOT / "ml" / "src" / "prevoir.py"
ML_PREVISION_ETAPES = ("telecharger", "verifier", "evaluer")


def cmd_ml_anomalies(_: argparse.Namespace) -> int:
    """Détection d'anomalies (IA-09) : règles et Isolation Forest sur les runs du simulateur ; écrit ml/evaluation/anomalies*."""
    if not ml_python().exists():
        print("ml/.venv est absent : lancer d'abord « ml-env » (scikit-learn y est installé avec ses empreintes).", file=sys.stderr)
        return 2
    return subprocess.run([str(ml_python()), str(ML_ANOMALIES)], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"}, check=False).returncode


def cmd_ml_sumo(args: argparse.Namespace) -> int:
    """Prototype SUMO (IA-11) : image Docker, simulation d'un carrefour, rejeu par le pipeline, comparaison avec le générateur v0."""
    require_docker()
    options = ["--graine", str(args.graine)] + (["--pile"] if args.pile else [])
    return subprocess.run([sys.executable, str(ML_SUMO), args.etape, *options], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"}, check=False).returncode


def cmd_ml_prevision(args: argparse.Namespace) -> int:
    """Prévision de vitesse (IA-10) : télécharger et contrôler METR-LA, le contrôler seulement, ou évaluer (écrit ml/evaluation/prevision*)."""
    if args.etape == "evaluer":
        if not ml_python().exists():
            print("ml/.venv est absent : lancer d'abord « ml-env » (scikit-learn et h5py y sont installés avec leurs empreintes).", file=sys.stderr)
            return 2
        interpreteur = str(ml_python())
    else:
        interpreteur = sys.executable  # télécharger et vérifier n'utilisent que la bibliothèque standard
    return subprocess.run([interpreteur, str(ML_PREVISION), args.etape], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"}, check=False).returncode


# --------------------------------------------------------------------------- registre des modèles (IA-04)
ML_REGISTRE = ROOT / "ml" / "src" / "registre_cli.py"
ML_REGISTRE_COMMANDES = ("importer-ia03", "lister", "en-service", "lignee", "charger")


def cmd_ml_registre(args: argparse.Namespace) -> int:
    """Lit ou alimente le registre des modèles (model_runs dans MongoDB, modèles dans var/models/) avec le compte svc_ml."""
    if not ml_python().exists():
        print("ml/.venv est absent : lancer d'abord « ml-env » (pymongo et scikit-learn y sont installés avec leurs empreintes).", file=sys.stderr)
        return 2
    require_env()
    environment = {**os.environ, "MONGO_URL": mongo_url(etl_environment(), "svc_ml", "MONGO_PASSWORD_ML"), "PYTHONUTF8": "1"}
    return subprocess.run([str(ml_python()), str(ML_REGISTRE), args.commande, *args.options], cwd=ROOT, env=environment, check=False).returncode


def cmd_ml_registre_essai(_: argparse.Namespace) -> int:
    """Tests du registre contre un vrai MongoDB jetable (projet Compose à part, compte svc_ml, validateur et index réels)."""
    if not ml_python().exists():
        print("ml/.venv est absent : lancer d'abord « ml-env ».", file=sys.stderr)
        return 2
    require_env()
    project = f"novaria-ml-{secrets.token_hex(3)}"
    ports = {"MONGO_PORT": str(free_port())}
    saved = {name: os.environ.get(name) for name in INTEGRATION_ISOLATION}
    os.environ.update({"COMPOSE_PROJECT_NAME": project, **ports})
    print(f"MongoDB jetable : projet Compose {project} (Mongo :{ports['MONGO_PORT']})")
    try:
        code = run_compose_step("up", "-d", "--wait", "mongo")
        if code != 0:
            return code
        adresse = mongo_url({**etl_environment(), **ports}, "svc_ml", "MONGO_PASSWORD_ML")
        environment = {**os.environ, "REGISTRE_MONGO_URL": adresse, "PYTHONUTF8": "1"}
        return subprocess.run([str(ml_python()), "-m", "unittest", "discover", "-s", "ml/tests", "-t", "ml", "-p", "test_registre.py", "-v"],
                              cwd=ROOT, env=environment, check=False).returncode
    finally:
        compose("down", "-v", "--remove-orphans", check=False)
        print(f"Projet {project} supprimé (conteneurs, réseau et volumes).")
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# --------------------------------------------------------------------------- pipeline MLSecOps (IA-05)
ML_PIPELINE = ROOT / "ml" / "src" / "executer_pipeline.py"
ML_PIPELINE_ETAPES = ("evaluer", "porte", "enregistrer", "tout")


def cmd_ml_pipeline(args: argparse.Namespace) -> int:
    """Pipeline MLSecOps en local : évaluer, porte (bloque sous le seuil), enregistrer ; registre en fichiers, ou MongoDB avec --mongo."""
    if not ml_python().exists():
        print("ml/.venv est absent : lancer d'abord « ml-env ».", file=sys.stderr)
        return 2
    environment = {**os.environ, "PYTHONUTF8": "1"}
    if args.mongo:
        require_env()
        environment["MONGO_URL"] = mongo_url(etl_environment(), "svc_ml", "MONGO_PASSWORD_ML")
    command = [str(ml_python()), str(ML_PIPELINE), args.etape]
    if args.sans_audit:
        command.append("--sans-audit")
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


# --------------------------------------------------------------------------- rapport hebdomadaire du robot (IA-07, FE-06)
RPA_DIR = ROOT / "automation" / "rpa"


def rpa_command(args: argparse.Namespace, env_values: dict[str, str], robot_installed: bool) -> list[str]:
    """Commande du robot : la suite Robot Framework si elle est installée (et sans --sans-robot), sinon le paquet seul."""
    gateway = env_values.get("GATEWAY_PORT", "8000")
    api = args.api or f"http://127.0.0.1:{gateway}"
    if robot_installed and not args.sans_robot:
        command = [sys.executable, "-m", "robot", "--outputdir", str(ROOT / "var" / "rpa"),
                   "--variable", f"API:{api}", "--variable", f"DOSSIER:{REPORTS_DIR}"]
        for name, value in (("DEBUT", args.debut), ("FIN", args.fin)):
            if value:
                command += ["--variable", f"{name}:{value}"]
        return [*command, str(RPA_DIR / "rapport_hebdomadaire.robot")]
    command = [sys.executable, "-m", "rapport", "--api", api, "--dossier", str(REPORTS_DIR)]
    for option, value in (("--debut", args.debut), ("--fin", args.fin)):
        if value:
            command += [option, value]
    return command


RPA_OBLIGATOIRES = ("NOVARIA_RPA_USER", "NOVARIA_RPA_PASSWORD")
# Reprises et notification par courriel : lues dans .env si elles n'y sont pas déjà dans l'environnement (jamais en argument).
RPA_FACULTATIVES = ("NOVARIA_RPA_TENTATIVES", "NOVARIA_RPA_ATTENTE_S", "NOVARIA_RPA_SMTP", "NOVARIA_RPA_DESTINATAIRE",
                    "NOVARIA_RPA_EXPEDITEUR", "NOVARIA_RPA_SMTP_UTILISATEUR", "NOVARIA_RPA_SMTP_MOT_DE_PASSE")


def rpa_environment(args: argparse.Namespace) -> tuple[dict[str, str], dict[str, str], bool]:
    """(environnement du robot, variables de .env, Robot Framework installé) : le compte de service vient de l'environnement ou de .env."""
    env_values = parse_env(ENV_FILE.read_text(encoding="utf-8")) if ENV_FILE.exists() else {}
    environment = dict(os.environ)
    for name in (*RPA_OBLIGATOIRES, *RPA_FACULTATIVES):
        if not environment.get(name) and env_values.get(name):
            environment[name] = env_values[name]
    for name in RPA_OBLIGATOIRES:
        if not environment.get(name):
            raise DevError(f"{name} est absent (variable d'environnement ou .env). Créer un compte en lecture seule : "
                           "python3 scripts/dev/dev.py user-create rpa-rapport --role viewer, puis renseigner les deux variables.")
    robot_installed = importlib.util.find_spec("robot") is not None
    if not robot_installed and not args.sans_robot:
        print("Robot Framework n'est pas installé : seul le paquet `rapport` est lancé "
              "(installer : pip install -r automation/rpa/requirements.txt).", file=sys.stderr)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(RPA_DIR), environment.get("PYTHONPATH")]))
    return environment, env_values, robot_installed


def cmd_rpa_report(args: argparse.Namespace) -> int:
    """Produit le rapport hebdomadaire et le dépose dans var/reports (la page « Rapports » l'affiche). Compte de service lu dans l'environnement ou .env."""
    environment, env_values, robot_installed = rpa_environment(args)
    return subprocess.run(rpa_command(args, env_values, robot_installed), cwd=ROOT, env=environment, check=False).returncode


def rpa_planner_command(args: argparse.Namespace, env_values: dict[str, str], robot_installed: bool) -> list[str]:
    """Le planificateur (`python -m rapport.planificateur`) autour de la commande de `rpa-report`."""
    command = [sys.executable, "-m", "rapport.planificateur", "--jour", args.jour, "--heure", args.heure, "--dossier", str(REPORTS_DIR)]
    if args.sans_rattrapage:
        command.append("--sans-rattrapage")
    if args.executions:
        command += ["--executions", str(args.executions)]
    return [*command, "--", *rpa_command(args, env_values, robot_installed)]


def cmd_rpa_planifier(args: argparse.Namespace) -> int:
    """Planifie le rapport chaque semaine sans cron ni Planificateur de tâches (processus au premier plan ; Ctrl+C l'arrête)."""
    environment, env_values, robot_installed = rpa_environment(args)
    return subprocess.run(rpa_planner_command(args, env_values, robot_installed), cwd=ROOT, env=environment, check=False).returncode


# --------------------------------------------------------------------------- dérive des entrées du modèle (IA-06)
def drift_check_command(args: argparse.Namespace) -> list[str]:
    """`docker compose exec` du script de dérive dans le conteneur du traitement (mêmes arguments que `python -m app.drift check`)."""
    command = ["exec", "-T", "traitement", "python", "-m", "app.drift", "check"]
    for option, value in (("--reference-run", args.reference_run), ("--current-run", args.current_run)):
        if value:
            command += [option, value]
    if args.json:
        command.append("--json")
    return command


def cmd_drift_check(args: argparse.Namespace) -> int:
    """Compare les entrées de l'exécution la plus récente à une exécution de référence ; code 1 si la dérive dépasse le seuil d'alerte (IA-06)."""
    require_env()
    return compose(*drift_check_command(args), check=False).returncode


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


def cmd_terraform_check(args: argparse.Namespace) -> int:
    """Contrôles Terraform sans compte AWS (LOC-06) ; la logique est dans terraform_check.py."""
    import terraform_check

    require_docker()
    root = ROOT / "infra" / "terraform"
    env_values = parse_env(ENV_FILE.read_text(encoding="utf-8")) if ENV_FILE.exists() else {}
    token = os.environ.get("SNYK_TOKEN") or env_values.get("SNYK_TOKEN")
    try:
        if args.lock:
            user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else None  # fichiers au nom de la personne
            steps = terraform_check.lock_steps(root, user)
        else:
            steps = terraform_check.build_steps(root, snyk_token=bool(token), with_snyk=not args.sans_snyk)
        print("Contrôles Terraform sans identifiant AWS (premier lancement : téléchargement du fournisseur AWS, plusieurs minutes) :")
        results = terraform_check.run_steps(steps, env=terraform_check.process_environment(token), verbose=args.verbose)
    except terraform_check.TerraformCheckError as error:
        raise DevError(str(error)) from error
    code = terraform_check.exit_code(results)
    if code == 1:
        print("ÉCHEC : au moins un contrôle a échoué (sortie ci-dessus).", file=sys.stderr)
    elif code == 2:
        print("INCOMPLET : un contrôle n'a pas été lancé. Définir SNYK_TOKEN, ou ajouter --sans-snyk pour l'écarter explicitement.", file=sys.stderr)
    elif args.lock:
        print("Verrous à jour : relire le diff de .terraform.lock.hcl puis le commiter.")
    else:
        print("Tous les contrôles ont réussi, sans identifiant AWS.")
    return code


def cmd_terraform_plan_hors_ligne(args: argparse.Namespace) -> int:
    """Plan Terraform hors ligne sur une copie jetable (CLD-17) : sans compte AWS, sans modifier le dépôt ; la logique est dans terraform_plan_hors_ligne.py."""
    import tempfile

    import terraform_plan_hors_ligne as plan

    require_docker()
    racine = ROOT / "infra" / "terraform"
    with tempfile.TemporaryDirectory(prefix="novaria-tf-") as temporaire:
        code, sortie = plan.executer(racine, args.mode, args.env, Path(temporaire))
    print(sortie)
    ecarts = plan.verdict(args.mode, code, sortie)
    for ecart in ecarts:
        print(f"ÉCART : {ecart}", file=sys.stderr)
    return 1 if ecarts else 0


def cmd_terraform_emulateur(args: argparse.Namespace) -> int:
    """Terraform appliqué à un émulateur d'API AWS local (Moto) puis plan rejoué : 0 changement ? (CLD-17) ; la logique est dans terraform_emulateur.py."""
    import tempfile

    import terraform_emulateur as emulateur

    require_docker()
    racine = ROOT / "infra" / "terraform"
    print(f"Terraform sur l'émulateur local Moto (réseau Docker interne, aucun appel vers AWS), environnement {args.env} :")
    with tempfile.TemporaryDirectory(prefix="novaria-tf-") as temporaire:
        resultats = emulateur.executer(racine, args.env, Path(temporaire))
    for resultat in resultats:
        print(f"  [{'OK' if resultat.ok else 'ÉCHEC'}] {resultat.etape.nom} (code {resultat.code})")
    if args.sortie:
        cible = Path(args.sortie)
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(emulateur.transcription(resultats, args.env, time.strftime('%Y-%m-%d')), encoding="utf-8", newline="\n")
        print(f"Compte rendu écrit : {cible}")
    ecarts = emulateur.verdict(resultats)
    for ecart in ecarts:
        print(f"ÉCART : {ecart}", file=sys.stderr)
    return 1 if ecarts or not resultats else 0


# --------------------------------------------------------------------------- prototype Big Data (DAT-08)
def cmd_bigdata_build(_: argparse.Namespace) -> int:
    """Construit l'image du prototype Big Data (PySpark en mode local, Java 21) ; la première fois, plusieurs minutes."""
    import bigdata_docker

    require_docker()
    return subprocess.run(bigdata_docker.commande_de_construction(ROOT), check=False).returncode


def cmd_bigdata(args: argparse.Namespace) -> int:
    """Lance le prototype dans son image : generer, nettoyer, verifier ou mesurer (voir data/bigdata/README.md)."""
    import bigdata_docker

    require_docker()
    arguments = [mot for mot in args.arguments if mot != "--"]
    if not arguments:
        raise DevError("Indiquer la commande du prototype, par exemple :  dev.py bigdata generer --jours 30")
    return subprocess.run(bigdata_docker.commande_de_lancement(ROOT, arguments, args.cpus, args.memoire), check=False).returncode


def cmd_bigdata_test(args: argparse.Namespace) -> int:
    """Lance les tests du prototype dans son image (PySpark et Java y sont : aucun test n'est ignoré)."""
    import bigdata_docker

    require_docker()
    return subprocess.run(bigdata_docker.commande_de_test(ROOT, args.cpus, args.memoire), check=False).returncode


# --------------------------------------------------------------------------- matrice d'accès et essais de refus (CLD-18)
def cmd_tableau_de_bord(args: argparse.Namespace) -> int:
    """Tableau de bord de pilotage (GES-11) : exigences, risques et livrables par jalon, recalculés depuis GitHub."""
    options = (["--ref", args.ref] if args.ref else []) + (["--local"] if args.local else []) + (["--json"] if args.json else []) + (["--ecrire"] if args.ecrire else [])
    script = ROOT / "scripts" / "github" / "tableau_de_bord.py"
    return subprocess.run([sys.executable, str(script), *options], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"}, check=False).returncode


def cmd_acces(args: argparse.Namespace) -> int:
    """Compare ops/matrice-acces.json à ce que la pile applique : essais autorisés et refusés sur l'API, PostgreSQL et MongoDB."""
    import acces

    require_env()
    require_docker()
    pile = acces.Pile(parse_env(ENV_FILE.read_text(encoding="utf-8")))
    print("Matrice d'accès de la pile locale : essais d'autorisation et de refus (la pile doit tourner : dev.py up).")
    essais, ecarts, incoherences = acces.executer(pile, afficher=print)
    print()
    for famille, accordes, attendus_accordes, refuses, attendus_refuses in acces.resume_par_famille(essais):
        print(f"  {famille:<24} accès accordés {accordes}/{attendus_accordes} · accès refusés {refuses}/{attendus_refuses}")
    print("\nUn essai autorisé et un essai refusé par sujet :")
    for sujet, (autorise, refuse) in acces.exemples_par_sujet(essais, ("api", "postgres (essai", "mongo (essai"), acces.charger()["api"]["exemples"]).items():
        for essai in (autorise, refuse):
            if essai:
                print(f"  [{'OK' if essai.ok else 'ÉCHEC'}] {sujet:<16} {'autorisé' if essai.attendu else 'refusé  '} {essai.operation} → {essai.detail}")
    if ecarts:
        print("\nÉcarts connus (contrôle prévu et absent, non compté comme un succès) :")
        for ecart in ecarts:
            print(f"  [ÉCART] {ecart.libelle}\n          {ecart.preuve}")
    echecs = [essai for essai in essais if not essai.ok]
    for ligne in incoherences:
        print(f"[ÉCHEC] matrice et contrats : {ligne}")
    for essai in echecs[: args.max_echecs]:
        print(f"[ÉCHEC] {essai.famille} · {essai.sujet} · {essai.ressource} · {essai.operation} : attendu {'accès' if essai.attendu else 'refus'}, {essai.detail}")
    total = len(essais)
    interdits = acces.accord_interdit(essais)
    print(f"\n{total - len(echecs)}/{total} essais conformes à la matrice, {len(ecarts)} écart(s) connu(s).")
    print(f"Accès interdits accordés : {len(interdits)} (critère de CLD-18 : 0).  Accès prévus refusés ou non concluants : {len(acces.refus_inattendu(essais))}.")
    return 1 if echecs or incoherences else 0


# --------------------------------------------------------------------------- sauvegarde planifiée et restauration vérifiée (CLD-15)
def _sauvegarde_module():
    import sauvegarde

    require_env()
    require_docker()
    return sauvegarde


def cmd_sauvegarde(_: argparse.Namespace) -> int:
    """Sauvegarde PostgreSQL et MongoDB avec manifeste (totaux et sommes de contrôle), puis conservation par paliers."""
    module = _sauvegarde_module()
    try:
        module.sauvegarder(module.Serveurs(ROOT))
    except module.Echec as erreur:
        raise DevError(str(erreur)) from erreur
    return 0


def cmd_sauvegarde_liste(args: argparse.Namespace) -> int:
    """Liste les sauvegardes, leur manifeste, et ce que la politique de conservation supprimerait (rien n'est supprimé)."""
    module = _sauvegarde_module()
    maintenant = datetime.now(timezone.utc)
    for base in ("postgres", "mongo"):
        existantes = module.lister(base, ROOT / "backups")
        garder = module.a_conserver(existantes, maintenant)
        print(f"{base} : {len(existantes)} sauvegarde(s), {len(garder)} à conserver")
        for nom, instant in sorted(existantes.items(), key=lambda element: element[1], reverse=True):
            manifeste = "manifeste" if module.chemin_manifeste(ROOT / "backups" / base / nom).is_file() else "SANS manifeste"
            print(f"  {instant:%Y-%m-%d %H:%M:%SZ}  {nom}  {manifeste}  {'conservée' if nom in garder else 'serait supprimée'}")
    return 0


def cmd_restauration(args: argparse.Namespace) -> int:
    """Restaure les dernières sauvegardes dans un environnement Docker isolé et compare les totaux au manifeste."""
    module = _sauvegarde_module()
    env = parse_env(ENV_FILE.read_text(encoding="utf-8"))
    fichiers = {base: ROOT / "backups" / base / nom for base, nom in (("postgres", args.postgres), ("mongo", args.mongo)) if nom}
    print("Restauration dans un environnement isolé (réseau interne, mots de passe aléatoires, supprimé à la fin).")
    afficher = lambda resultat: print(module.ligne(resultat), flush=True)  # noqa: E731
    resultats = module.restaurer_et_verifier(fichiers=fichiers, nom_base_mongo=env.get("MONGO_DB", "novaria"), administrateur_pg=env.get("POSTGRES_USER", "novaria_admin"), afficher=afficher)
    if args.controles_negatifs and all(resultat.ok for resultat in resultats):
        print("Contrôles négatifs (une panne injectée doit être détectée) :")
        resultats += module.controles_negatifs(nom_base_mongo=env.get("MONGO_DB", "novaria"), administrateur_pg=env.get("POSTGRES_USER", "novaria_admin"), afficher=afficher)
    echecs = [resultat.cas for resultat in resultats if not resultat.ok]
    print(f"{len(resultats) - len(echecs)}/{len(resultats)} cas satisfaits." + (f" Échecs : {', '.join(echecs)}." if echecs else ""))
    return 1 if echecs else 0


def cmd_sauvegarde_planifier(args: argparse.Namespace) -> int:
    """Planifie la sauvegarde sans cron : attend le créneau, sauvegarde, rattrape une sauvegarde manquante au démarrage."""
    module = _sauvegarde_module()
    env = parse_env(ENV_FILE.read_text(encoding="utf-8"))

    def cycle() -> None:
        module.sauvegarder(module.Serveurs(ROOT))
        if args.verifier:
            resultats = module.restaurer_et_verifier(nom_base_mongo=env.get("MONGO_DB", "novaria"), administrateur_pg=env.get("POSTGRES_USER", "novaria_admin"), afficher=lambda r: print(module.ligne(r), flush=True))
            if not all(resultat.ok for resultat in resultats):
                raise module.Echec("la restauration de contrôle a échoué")

    def derniere() -> dict:
        resultat = {}
        for base in ("postgres", "mongo"):
            existantes = module.lister(base, ROOT / "backups")
            resultat[base] = max(existantes.values()) if existantes else None
        return resultat

    reussis = module.planifier(cycle, heure=args.heure, toutes_les_s=args.toutes_les, executions=args.executions,
                               sans_rattrapage=args.sans_rattrapage, derniere=derniere)
    print(f"{reussis} sauvegarde(s) planifiée(s) réussie(s).")
    return 0


# --------------------------------------------------------------------------- panne contrôlée et observatoire (CLD-14)
def _observatoire():
    import observatoire

    require_env()
    require_docker()
    env = parse_env(ENV_FILE.read_text(encoding="utf-8"))
    return observatoire, observatoire.Observatoire(observatoire.charger_config(), observatoire.Docker(ROOT), env)


def cmd_observatoire(args: argparse.Namespace) -> int:
    """Sert l'interface graphique de l'observatoire des pannes sur 127.0.0.1 (la pile doit tourner : dev.py up)."""
    module, obs = _observatoire()
    module.servir(obs, args.port)
    return 0


def cmd_panne(args: argparse.Namespace) -> int:
    """Arrête un service, attend l'alarme, retrace alarme, journal et cause, rétablit, puis affiche le rapport (la pile doit tourner)."""
    module, obs = _observatoire()
    if args.service not in obs.config["services"]:
        raise DevError(f"Service inconnu : {args.service}. Services : {', '.join(obs.config['services'])}.")
    obs.demarrer()
    try:
        obs.arret.wait(float(obs.config["periode_s"]) * 2)  # deux tours de mesure : la pile saine est connue avant la panne
        try:
            rapport = module.rejouer_panne(obs, args.service, duree_s=args.duree, trafic=args.trafic, mode=args.mode)
        except module.ErreurPanne as erreur:
            raise DevError(str(erreur)) from erreur
    finally:
        obs.arreter_mesure()
    print()
    print(module.rapport_texte(rapport))
    print(f"\nRetour à la normale (toutes les alarmes à OK) : {'oui' if rapport['tout_est_ok'] else 'NON'}")
    return 0 if rapport["alarmes"] and rapport["tout_est_ok"] else 1


# --------------------------------------------------------------------------- parcours de bout en bout (CLD-13)
def cmd_parcours(args: argparse.Namespace) -> int:
    """Rejoue le parcours nominal (donnée brute, entrepôt, API, tableau de bord) et les cas d'échec sur la pile locale."""
    import parcours

    require_env()
    require_docker()
    ids = tuple(item.upper() for item in args.cas) or None
    inconnus = [item for item in ids or () if item not in {cas[0] for cas in parcours.CAS}]
    if inconnus:
        raise DevError(f"Cas inconnu : {', '.join(inconnus)}. Cas possibles : {', '.join(cas[0] for cas in parcours.CAS)}.")
    pile = parcours.Pile(parse_env(ENV_FILE.read_text(encoding="utf-8")))
    print("Parcours de bout en bout sur la pile locale (la pile doit tourner : dev.py up).")
    resultats = parcours.executer(pile, ids, afficher=lambda resultat: print(parcours.ligne(resultat), flush=True))
    echecs = [resultat.cas for resultat in resultats if not resultat.ok]
    print(f"{len(resultats) - len(echecs)}/{len(resultats)} cas satisfaits." + (f" Échecs : {', '.join(echecs)}." if echecs else ""))
    return 1 if echecs else 0


def cmd_flux_complet(args: argparse.Namespace) -> int:
    """Rejoue le flux complet (capteur simulé jusqu'à la commande de feux) et les cas d'échec sur la pile locale (MS-15)."""
    import flux_complet

    require_env()
    require_docker()
    ids = tuple(item.upper() for item in args.cas) or None
    inconnus = [item for item in ids or () if item not in {cas[0] for cas in flux_complet.CAS}]
    if inconnus:
        raise DevError(f"Cas inconnu : {', '.join(inconnus)}. Cas possibles : {', '.join(cas[0] for cas in flux_complet.CAS)}.")
    pile = flux_complet.Pile(parse_env(ENV_FILE.read_text(encoding="utf-8")))
    print("Flux complet sur la pile locale (la pile doit tourner : dev.py up). Les cas d'échec arrêtent puis redémarrent des conteneurs ; environ 10 minutes en tout.")
    resultats = flux_complet.executer(pile, ids, afficher=lambda resultat: print(flux_complet.ligne(resultat), flush=True))
    echecs = [resultat.cas for resultat in resultats if not resultat.ok]
    print(f"{len(resultats) - len(echecs)}/{len(resultats)} cas satisfaits." + (f" Échecs : {', '.join(echecs)}." if echecs else ""))
    return 1 if echecs else 0


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


STUB_PORT = 8001  # la maquette des prévisions : le proxy de Vite la vise avec `front-dev --stub`
REPORT_STUB_PORT = 8002  # la maquette des rapports : le proxy de Vite la vise avec `front-dev --report-stub`


def cmd_forecast_stub(args: argparse.Namespace) -> int:
    """Lance la MAQUETTE de GET /api/v1/forecasts (FE-05) devant l'API : la route n'est pas encore implémentée côté serveur."""
    import forecast_stub

    return forecast_stub.main(["--upstream", f"http://127.0.0.1:{API_PORT}", "--port", str(STUB_PORT), "--back-minutes", str(args.back_minutes)])


def cmd_report_stub(args: argparse.Namespace) -> int:
    """Lance la MAQUETTE de GET /api/v1/reports (FE-06) devant l'API : les routes et le robot n'existent pas encore."""
    import report_stub

    # Derrière la maquette des prévisions, les deux pages se testent ensemble : chaque maquette ne sert que sa route.
    upstream_port = STUB_PORT if args.behind_forecast_stub else API_PORT
    return report_stub.main(["--upstream", f"http://127.0.0.1:{upstream_port}", "--port", str(REPORT_STUB_PORT), "--count", str(args.count)])


def cmd_front_dev(args: argparse.Namespace) -> int:
    """Lance le front-end (Vite, http://localhost:5173) ; installe les dépendances npm la première fois."""
    npm = shutil.which("npm")
    if npm is None:
        raise DevError("npm est absent (Node.js 22 ou plus). Voir docs/08-exploitation/poste-de-travail.md.")
    if not (FRONTEND_DIR / "node_modules").is_dir():
        code = subprocess.run([npm, "ci"], cwd=FRONTEND_DIR, check=False).returncode
        if code:
            return code
    environment = dict(os.environ)
    if args.stub and args.report_stub:
        raise DevError("--stub et --report-stub s'excluent. Pour les deux pages : report-stub --behind-forecast-stub, puis front-dev --report-stub.")
    if args.stub:
        environment["API_TARGET"] = f"http://localhost:{STUB_PORT}"
        print(f"Les appels /api passent par la maquette des prévisions (forecast-stub, port {STUB_PORT}).")
    if args.report_stub:
        environment["API_TARGET"] = f"http://localhost:{REPORT_STUB_PORT}"
        print(f"Les appels /api passent par la maquette des rapports (report-stub, port {REPORT_STUB_PORT}).")
    print(f"Front-end : http://localhost:5173  (Ctrl+C pour arrêter ; l'API doit tourner : api-run, sur le port {API_PORT})")
    try:
        return subprocess.run([npm, "run", "dev"], cwd=FRONTEND_DIR, env=environment, check=False).returncode
    except KeyboardInterrupt:
        return 0


# --------------------------------------------------------------------------- tests d'intégration (BE-07)
# Paquets que les tests de services/traitement importent et que l'interpréteur courant doit avoir.
INTEGRATION_PACKAGES = ("pytest", "pytest_cov", "sqlalchemy", "alembic", "psycopg", "pymongo", "jwt", "argon2", "fastapi")
INTEGRATION_ISOLATION = ("COMPOSE_PROJECT_NAME", "POSTGRES_PORT", "MONGO_PORT", "KAFKA_PORT")
# Paquets que les tests de services/collecte importent (MS-08) : le client Kafka, MongoDB, le contrat.
COLLECTE_PACKAGES = ("pytest", "pytest_cov", "kafka", "pymongo", "fastapi", "httpx", "jsonschema", "referencing", "yaml")
COLLECTE_SERVICE_DIR = ROOT / "services" / "collecte"
FLUX_PACKAGES = (*INTEGRATION_PACKAGES, "kafka", "jsonschema", "referencing")
# Paquets que les tests de services/alerte importent (MS-11) : PostgreSQL, le client Kafka, les jetons, l'API.
ALERTE_PACKAGES = ("pytest", "pytest_cov", "kafka", "psycopg", "psycopg_pool", "jwt", "fastapi", "uvicorn",
                   "httpx", "jsonschema", "referencing", "yaml")
ALERTE_SERVICE_DIR = ROOT / "services" / "alerte"
# Paquets que les tests de services/reponse importent (MS-12) : le client Kafka, MongoDB, les jetons, l'API.
REPONSE_PACKAGES = ("pytest", "pytest_cov", "kafka", "pymongo", "jwt", "fastapi", "uvicorn",
                    "httpx", "jsonschema", "referencing", "yaml")
REPONSE_SERVICE_DIR = ROOT / "services" / "reponse"


def free_port() -> int:
    """Un port libre de 127.0.0.1 (le système l'attribue ; il peut être repris avant le démarrage du conteneur, très rare)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def mongo_admin_url(env: dict[str, str]) -> str:
    """Adresse MongoDB de l'administrateur : efface les traces d'essai (les comptes de service ne peuvent pas supprimer)."""
    database = env["MONGO_DB"]
    admin_password = urllib.parse.quote(env["MONGO_ROOT_PASSWORD"], safe="")
    return (f"mongodb://{env['MONGO_ROOT_USER']}:{admin_password}"
            f"@127.0.0.1:{env.get('MONGO_PORT') or '27017'}/{database}?authSource=admin")


def collecte_environment(env: dict[str, str]) -> dict[str, str]:
    """Variables que lisent les tests d'intégration de services/collecte (tests/integration/stack.py).

    - Kafka : l'adresse publiée sur le poste (KAFKA_PORT du projet jetable) ;
    - MongoDB : le compte `svc_collecte` (droits de production : find et insert) et, pour effacer, l'administrateur.
    """
    for name in ("MONGO_ROOT_USER", "MONGO_ROOT_PASSWORD", "MONGO_DB"):
        if not env.get(name):
            raise DevError(f"Variable absente de .env : {name} (init-env --force puis db-reset).")
    return {
        "NOVARIA_TEST_KAFKA_BOOTSTRAP": f"127.0.0.1:{env.get('KAFKA_PORT') or '9094'}",
        "NOVARIA_TEST_MONGO_URL": mongo_url(env, "svc_collecte", "MONGO_PASSWORD_COLLECTE"),
        "NOVARIA_TEST_MONGO_ADMIN_URL": mongo_admin_url(env),
    }


def reponse_environment(env: dict[str, str]) -> dict[str, str]:
    """Variables que lisent les tests d'intégration de la réponse (services/reponse/tests/integration/stack.py).

    - Kafka : l'adresse publiée sur le poste (KAFKA_PORT du projet jetable) ;
    - MongoDB : le compte `svc_reponse` (droits de production : find et insert sur `audit_logs`) et l'administrateur,
      qui relit, nettoie et vérifie que le compte du service ne peut ni modifier ni supprimer une entrée.
    """
    for name in ("MONGO_ROOT_USER", "MONGO_ROOT_PASSWORD", "MONGO_DB"):
        if not env.get(name):
            raise DevError(f"Variable absente de .env : {name} (init-env --force puis db-reset).")
    return {
        "NOVARIA_TEST_KAFKA_BOOTSTRAP": f"127.0.0.1:{env.get('KAFKA_PORT') or '9094'}",
        "NOVARIA_TEST_REPONSE_MONGO_URL": mongo_url(env, "svc_reponse", "MONGO_PASSWORD_REPONSE"),
        "NOVARIA_TEST_REPONSE_MONGO_ADMIN_URL": mongo_admin_url(env),
    }


def flux_environment(env: dict[str, str]) -> dict[str, str]:
    """Variables que lisent les tests d'intégration du flux (services/traitement/tests/integration/stack_flux.py).

    - Kafka : l'adresse publiée sur le poste (KAFKA_PORT du projet jetable) ;
    - PostgreSQL : le compte `svc_traitement` (droits de production sur `dwh`), le compte `svc_lecture` (lecture seule,
      celui de l'API) et l'administrateur, qui relit et nettoie ;
    - MongoDB : le compte `svc_traitement` (rejects : find et insert ; processing_stats : find, insert, update) et l'administrateur.
    """
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "MONGO_ROOT_USER", "MONGO_ROOT_PASSWORD", "MONGO_DB"):
        if not env.get(name):
            raise DevError(f"Variable absente de .env : {name} (init-env --force puis db-reset).")
    sqlalchemy = ("postgresql://", "postgresql+psycopg://")
    return {
        "NOVARIA_TEST_FLUX_KAFKA": f"127.0.0.1:{env.get('KAFKA_PORT') or '9094'}",
        "NOVARIA_TEST_FLUX_POSTGRES_URL": postgres_url(env, "svc_traitement", "PG_PASSWORD_TRAITEMENT").replace(*sqlalchemy, 1),
        "NOVARIA_TEST_FLUX_POSTGRES_READ_URL": postgres_url(env, "svc_lecture", "PG_PASSWORD_LECTURE").replace(*sqlalchemy, 1),
        "NOVARIA_TEST_FLUX_POSTGRES_ADMIN_URL": postgres_url(env, env["POSTGRES_USER"], "POSTGRES_PASSWORD").replace(*sqlalchemy, 1),
        "NOVARIA_TEST_FLUX_MONGO_URL": mongo_url(env, "svc_traitement", "MONGO_PASSWORD_TRAITEMENT"),
        "NOVARIA_TEST_FLUX_MONGO_ADMIN_URL": mongo_admin_url(env),
    }


def alerte_environment(env: dict[str, str]) -> dict[str, str]:
    """Variables que lisent les tests d'intégration de l'alerte (services/alerte/tests/integration/stack.py).

    - Kafka : l'adresse publiée sur le poste (KAFKA_PORT du projet jetable) ;
    - PostgreSQL : le compte `svc_alerte` (droits de production sur `alertes`, ceux du service) et l'administrateur,
      qui relit, nettoie et applique les essais de contraintes.
    """
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        if not env.get(name):
            raise DevError(f"Variable absente de .env : {name} (init-env --force puis db-reset).")
    return {
        "NOVARIA_TEST_KAFKA_BOOTSTRAP": f"127.0.0.1:{env.get('KAFKA_PORT') or '9094'}",
        "NOVARIA_TEST_ALERTE_POSTGRES_URL": postgres_url(env, "svc_alerte", "PG_PASSWORD_ALERTE"),
        "NOVARIA_TEST_ALERTE_POSTGRES_ADMIN_URL": postgres_url(env, env["POSTGRES_USER"], "POSTGRES_PASSWORD"),
    }


def integration_environment(env: dict[str, str]) -> dict[str, str]:
    """Variables que lisent les tests d'intégration (tests/integration/postgres.py et mongo.py).

    - PostgreSQL : le compte administrateur, qui crée puis supprime une base jetable par test ;
    - MongoDB : le compte `svc_backend` (droits de production de l'audit) et, pour effacer les traces d'essai, l'administrateur.
    """
    for name in ("POSTGRES_USER", "MONGO_ROOT_USER", "MONGO_ROOT_PASSWORD", "MONGO_DB"):
        if not env.get(name):
            raise DevError(f"Variable absente de .env : {name} (init-env --force puis db-reset).")
    postgres = postgres_url(env, env["POSTGRES_USER"], "POSTGRES_PASSWORD")
    return {
        "NOVARIA_TEST_POSTGRES_ADMIN_URL": postgres.replace("postgresql://", "postgresql+psycopg://", 1),
        "NOVARIA_TEST_MONGO_URL": mongo_url(env, "svc_backend", "MONGO_PASSWORD_BACKEND"),
        "NOVARIA_TEST_MONGO_ADMIN_URL": mongo_admin_url(env),
    }


def cmd_test_integration(args: argparse.Namespace) -> int:
    """Toute la suite d'un service, tests d'intégration compris, contre ses bases et son bus en conteneur.

    `--service traitement` (défaut, BE-07) : PostgreSQL et MongoDB. `--service collecte` (MS-08) : Kafka (sujets
    créés) et MongoDB. `--service flux` (MS-09) : PostgreSQL (migrations appliquées), MongoDB et Kafka (sujets
    créés), avec les comptes de service réels. `--service alerte` (MS-11) : PostgreSQL (migrations appliquées) et
    Kafka (sujets créés), avec le compte `svc_alerte`. `--service reponse` (MS-12) : Kafka (sujets créés) et MongoDB,
    avec le compte `svc_reponse`. Les conteneurs vivent dans un projet Compose jetable (nom et ports
    propres) : les données du poste ne sont pas touchées. Le projet est supprimé à la fin, volumes compris, sauf avec
    --keep. Le rapport de couverture est celui de pytest (terminal et coverage.xml du service) ; les options après
    `--` vont à pytest.
    """
    require_env()
    service = getattr(args, "service", "traitement")
    collecte, flux, alerte = service == "collecte", service == "flux", service == "alerte"
    reponse = service == "reponse"
    packages = (COLLECTE_PACKAGES if collecte else ALERTE_PACKAGES if alerte else REPONSE_PACKAGES if reponse
                else FLUX_PACKAGES if flux else INTEGRATION_PACKAGES)
    requirements = f"services/{service if collecte or alerte or reponse else 'traitement'}/requirements-dev.txt"
    for package in packages:
        if importlib.util.find_spec(package) is None:
            raise DevError(f"{package} est absent. L'installer :  {Path(sys.executable).name} -m pip install -r {requirements}")
    project = f"novaria-it-{secrets.token_hex(3)}"
    saved = {name: os.environ.get(name) for name in INTEGRATION_ISOLATION}
    ports = {} if alerte else {"MONGO_PORT": str(free_port())}
    if collecte or reponse:
        ports["KAFKA_PORT"] = str(free_port())
    elif alerte:
        ports.update({"POSTGRES_PORT": str(free_port()), "KAFKA_PORT": str(free_port())})
    elif flux:
        ports.update({"POSTGRES_PORT": str(free_port()), "KAFKA_PORT": str(free_port())})
    else:
        ports["POSTGRES_PORT"] = str(free_port())
    os.environ.update({"COMPOSE_PROJECT_NAME": project, **ports})
    shown = ", ".join(f"{name.removesuffix('_PORT').title()} :{port}" for name, port in ports.items())
    label = ("Kafka et MongoDB" if collecte or reponse else "PostgreSQL et Kafka" if alerte
             else "PostgreSQL, MongoDB et Kafka" if flux else "Bases")
    print(f"{label} jetables : projet Compose {project} ({shown})")
    try:
        containers = (("kafka", "mongo") if collecte or reponse else ("postgres", "kafka") if alerte
                      else ("postgres", "mongo", "kafka") if flux else ("postgres", "mongo"))
        code = run_compose_step("up", "-d", "--wait", *containers)
        if code != 0:
            return code
        if flux or alerte:
            code = run_compose_step("run", "--rm", "db-migrate")
            if code != 0:
                return code
        if collecte or flux or alerte or reponse:
            rows, failures = kafka_topic_rows()
            print("\n".join(rows))
            if failures:
                return 1
        build = (collecte_environment if collecte else alerte_environment if alerte
                 else reponse_environment if reponse else flux_environment if flux else integration_environment)
        # Les ports du projet jetable priment, même si .env n'a pas la ligne (KAFKA_PORT est facultatif) :
        # sinon les tests viseraient le port habituel du poste, où rien n'écoute.
        environment = {**os.environ, **build({**etl_environment(), **ports}), "PYTHONUTF8": "1"}
        pytest_args = [item for item in args.pytest_args if item != "--"]
        return subprocess.run([sys.executable, "-m", "pytest", *pytest_args],
                              cwd=(COLLECTE_SERVICE_DIR if collecte else ALERTE_SERVICE_DIR if alerte
                                   else REPONSE_SERVICE_DIR if reponse else APP_SERVICE_DIR),
                              env=environment, check=False).returncode
    finally:
        if args.keep:
            print(f"Conteneurs conservés (projet {project}). Les supprimer :  docker compose -p {project} down -v")
        else:
            compose("down", "-v", "--remove-orphans", check=False)
            print(f"Projet {project} supprimé (conteneurs, réseau et volumes).")
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


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
    it = add("test-integration", cmd_test_integration,
             "tests d'un service contre ses bases et son bus en conteneur (projet jetable) + rapport de couverture")
    it.add_argument("--service", choices=["traitement", "collecte", "flux", "alerte", "reponse"], default="traitement",
                    help="traitement : PostgreSQL et MongoDB (BE-07) ; collecte : Kafka et MongoDB (MS-08) ; "
                         "flux : PostgreSQL migré, MongoDB et Kafka (MS-09) ; alerte : PostgreSQL migré et Kafka (MS-11) ; "
                         "reponse : Kafka et MongoDB (MS-12)")
    it.add_argument("--keep", action="store_true", help="laisse les conteneurs du projet jetable en marche à la fin")
    it.add_argument("pytest_args", nargs=argparse.REMAINDER, help="options de pytest, après -- (par exemple -- -k audit)")
    add("dev-deps", cmd_dev_deps, "installe les paquets Python de l'API de traitement et de l'ETL dans l'interpréteur courant")
    add("api-run", cmd_api_run, "lance l'API de traitement sur http://127.0.0.1:8000 (tableau de bord en local)")
    front = add("front-dev", cmd_front_dev, "lance le front-end (Vite) sur http://localhost:5173")
    front.add_argument("--stub", action="store_true", help="les appels /api passent par la maquette des prévisions (forecast-stub)")
    front.add_argument("--report-stub", action="store_true", help="les appels /api passent par la maquette des rapports (report-stub)")
    stub = add("forecast-stub", cmd_forecast_stub, "lance la MAQUETTE de GET /api/v1/forecasts devant l'API (route non implémentée côté serveur)")
    stub.add_argument("--back-minutes", type=int, default=60, help="émission décalée avant la fin des données, pour avoir un observé à comparer (60)")
    reports = add("report-stub", cmd_report_stub, "lance la MAQUETTE de GET /api/v1/reports devant l'API (routes et robot absents côté serveur)")
    reports.add_argument("--count", type=int, default=3, help="nombre de rapports fictifs ; 0 : liste vide (3)")
    reports.add_argument("--behind-forecast-stub", action="store_true", help="se place devant la maquette des prévisions au lieu de l'API (les deux pages ensemble)")
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
    dataset = add("dataset-build", cmd_dataset_build, "construit le jeu d'entraînement v1 (IA-08) dans data/datasets/novaria-congestion-v1/, avec sa fiche de provenance")
    dataset.add_argument("--sortie", type=Path, help="dossier de sortie (data/datasets/novaria-congestion-v1 par défaut)")
    reference = add("reference-mesure", cmd_reference_mesure, "mesure la règle de seuils (ADR-028) sur l'entraînement et la validation du jeu v1 (IA-01) ; le test n'est pas lisible")
    reference.add_argument("--sensibilite", action="store_true", help="ajoute les variations d'un réglage à la fois")
    reference.add_argument("--json", action="store_true", help="rapport JSON")
    preparation = add("preparation-check", cmd_preparation_check, "vérifie le découpage et les variables du jeu v1 (IA-02) : variables permises, aucune fuite du futur, empreinte du découpage ; le test n'est pas lu")
    preparation.add_argument("--json", action="store_true", help="rapport JSON")
    add("ml-env", cmd_ml_env, "crée ml/.venv et y installe scikit-learn depuis ml/requirements.txt (empreintes exigées)")
    train = add("ml-train", cmd_ml_train, "entraînement et comparaison (IA-03) : validation, test (lu une seule fois) ou rapport ; nécessite ml-env")
    train.add_argument("etape", choices=ML_ETAPES, help="validation : réglage et choix ; test : lecture unique ; rapport : ml/evaluation/resultats.md")
    add("ml-anomalies", cmd_ml_anomalies, "détection d'anomalies (IA-09) : règles robustes et Isolation Forest sur les anomalies injectées (environ 1 minute) ; écrit ml/evaluation/anomalies*.{json,md} ; nécessite ml-env")
    sumo = add("ml-sumo", cmd_ml_sumo, "prototype SUMO (IA-11) : image, calibrer, simuler, rejouer [--pile], comparer ; SUMO tourne dans Docker, le reste en bibliothèque standard (sans ml-env)")
    sumo.add_argument("etape", choices=ML_SUMO_ETAPES, help="image : construit novaria-sumo:1.28.0 ; simuler : 5 h du carrefour INT_01 ; rejouer : moteur de fenêtres (--pile : aussi la pile Docker) ; comparer : ml/evaluation/sumo*")
    sumo.add_argument("--graine", type=int, default=42, help="graine de SUMO (défaut 42) ; une graine neuve donne un run que la collecte n'a jamais vu")
    sumo.add_argument("--pile", action="store_true", help="rejouer : publier aussi sur la collecte (la pile doit tourner : dev.py up)")
    prevision = add("ml-prevision", cmd_ml_prevision, "prévision de vitesse (IA-10) : telecharger et verifier METR-LA (empreinte SHA-256, sans ml-env), evaluer (environ 5 minutes ; nécessite ml-env)")
    prevision.add_argument("etape", choices=ML_PREVISION_ETAPES, help="telecharger : metr-la.h5 (57 Mo) ; verifier : taille et SHA-256 ; evaluer : ml/evaluation/prevision*.{json,md}")
    registre = add("ml-registre", cmd_ml_registre, "registre des modèles (IA-04) : importer-ia03, lister, en-service, lignee <run> [--jeu], charger ; nécessite la pile (db-up) et ml-env")
    registre.add_argument("commande", choices=ML_REGISTRE_COMMANDES)
    registre.add_argument("options", nargs=argparse.REMAINDER, help="arguments de la commande (lignee <run> --jeu)")
    add("ml-registre-essai", cmd_ml_registre_essai, "tests du registre contre un MongoDB jetable (projet Compose à part, supprimé ensuite) ; nécessite Docker et ml-env")
    pipeline = add("ml-pipeline", cmd_ml_pipeline, "pipeline MLSecOps (IA-05) : evaluer, porte (bloque un modèle sous le seuil), enregistrer, ou tout ; code 1 si la porte est fermée")
    pipeline.add_argument("etape", nargs="?", default="tout", choices=ML_PIPELINE_ETAPES)
    pipeline.add_argument("--mongo", action="store_true", help="écrit les runs dans model_runs (MongoDB, compte svc_ml) au lieu de var/pipeline/model_runs/")
    pipeline.add_argument("--sans-audit", action="store_true", help="n'appelle pas pip-audit (S4 reste « non vérifié »)")
    planifier = add("rpa-planifier", cmd_rpa_planifier, "planifie le rapport hebdomadaire (IA-07) sans cron : attend le créneau, rattrape un rapport manquant au démarrage")
    planifier.add_argument("--jour", default="lundi", help="jour de la semaine (lundi par défaut)")
    planifier.add_argument("--heure", default="07:00", metavar="HH:MM", help="heure du poste (07:00 par défaut)")
    planifier.add_argument("--sans-rattrapage", action="store_true", help="n'attend que le créneau, même si le rapport de la semaine manque")
    planifier.add_argument("--executions", type=int, help="s'arrête après ce nombre de lancements (essai)")
    planifier.add_argument("--debut", metavar="AAAA-MM-JJ", help="période fixe au lieu de la semaine précédente (essai)")
    planifier.add_argument("--fin", metavar="AAAA-MM-JJ", help="fin exclue de la période fixe (essai)")
    planifier.add_argument("--api", help="adresse de la passerelle (http://127.0.0.1:<GATEWAY_PORT> par défaut)")
    planifier.add_argument("--sans-robot", action="store_true", help="lance le paquet Python seul, sans Robot Framework")
    rpa = add("rpa-report", cmd_rpa_report, "produit le rapport hebdomadaire (robot, IA-07) et le dépose dans var/reports ; la page Rapports l'affiche")
    rpa.add_argument("--debut", metavar="AAAA-MM-JJ", help="début de la période (la semaine précédente par défaut)")
    rpa.add_argument("--fin", metavar="AAAA-MM-JJ", help="fin exclue (début + 7 jours par défaut)")
    rpa.add_argument("--api", help="adresse de la passerelle (http://127.0.0.1:<GATEWAY_PORT> par défaut)")
    rpa.add_argument("--sans-robot", action="store_true", help="lance le paquet Python seul, sans Robot Framework")
    drift = add("drift-check", cmd_drift_check, "script de dérive : compare les entrées de l'exécution la plus récente à une référence (code 1 : dérive)")
    drift.add_argument("--reference-run", metavar="RUN_ID", help="exécution de référence (DRIFT_REFERENCE_RUN_ID par défaut)")
    drift.add_argument("--current-run", metavar="RUN_ID", help="exécution courante (la plus récente par défaut)")
    drift.add_argument("--json", action="store_true", help="écrit le rapport en JSON")
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
    tf = add("terraform-check", cmd_terraform_check, "contrôles Terraform sans compte AWS : fmt, init, validate, tflint, Snyk IaC (Docker)")
    tf.add_argument("--sans-snyk", action="store_true", help="écarte l'analyse Snyk IaC (le résultat reste « incomplet » dans le compte rendu de l'issue)")
    tf.add_argument("--lock", action="store_true", help="régénère .terraform.lock.hcl (réseau nécessaire) au lieu de contrôler")
    tf.add_argument("--verbose", action="store_true", help="montre la sortie de chaque outil, pas seulement celle des échecs")
    tp = add("terraform-plan-hors-ligne", cmd_terraform_plan_hors_ligne, "plan Terraform hors ligne sur une copie jetable, sans compte AWS : ce qui serait créé, et ce que les protections refusent de détruire (CLD-17, Docker)")
    tp.add_argument("--mode", choices=("plan", "destruction-protegee", "bascule-variable"), default="plan", help="plan : premier plan, état vide ; destruction-protegee : état fictif, la destruction est refusée ; bascule-variable : protected = false, toujours refusé")
    tp.add_argument("--env", choices=("dev", "demo"), default="dev", help="environnement Terraform (dev par défaut ; les modes d'état fictif ne visent que dev)")
    te = add("terraform-emulateur", cmd_terraform_emulateur, "Terraform appliqué à l'émulateur d'API AWS Moto (local, ouvert), puis plan rejoué : 0 changement ? (CLD-17, Docker)")
    te.add_argument("--env", choices=("dev", "demo"), default="dev", help="environnement Terraform (dev : protégé ; demo : jetable)")
    te.add_argument("--sortie", help="écrit le compte rendu étape par étape dans ce fichier")
    bd = add("bigdata-build", cmd_bigdata_build, "construit l'image du prototype Big Data, PySpark local (DAT-08, Docker)")
    bd = add("bigdata", cmd_bigdata, "lance le prototype Big Data dans son image : generer, nettoyer, verifier, mesurer (Docker)")
    bd.add_argument("--cpus", default="4", help="cœurs alloués au conteneur (4 par défaut)")
    bd.add_argument("--memoire", default="6g", help="mémoire allouée au conteneur (6g par défaut)")
    bd.add_argument("arguments", nargs=argparse.REMAINDER, help="arguments de « python -m bigdata », après -- (par exemple -- mesurer --jours 7)")
    bdt = add("bigdata-test", cmd_bigdata_test, "tests du prototype Big Data dans son image (Docker)")
    bdt.add_argument("--cpus", default="4", help="cœurs alloués au conteneur (4 par défaut)")
    bdt.add_argument("--memoire", default="6g", help="mémoire allouée au conteneur (6g par défaut)")
    tdb = add("tableau-de-bord", cmd_tableau_de_bord, "tableau de bord de pilotage (GES-11) : exigences vérifiées, risques traités, livrables par jalon, recalculés depuis GitHub")
    tdb.add_argument("--ref", help="branche, étiquette ou empreinte lue sur GitHub (main par défaut)")
    tdb.add_argument("--local", action="store_true", help="lit exigences.md et registre-risques.md dans la copie de travail")
    tdb.add_argument("--json", action="store_true", help="sortie JSON")
    tdb.add_argument("--ecrire", action="store_true", help="met à jour le bloc mesuré de docs/07-gestion/tableau-de-bord.md")
    ac = add("acces", cmd_acces, "essais d'autorisation et de refus : compare la matrice d'accès à l'API, PostgreSQL et MongoDB (CLD-18)")
    ac.add_argument("--max-echecs", type=int, default=20, help="nombre d'échecs détaillés (20 par défaut)")
    sv = add("sauvegarde", cmd_sauvegarde, "sauvegarde PostgreSQL et MongoDB avec manifeste, puis conservation par paliers (CLD-15)")
    add("sauvegarde-liste", cmd_sauvegarde_liste, "liste les sauvegardes et ce que la politique de conservation supprimerait (CLD-15)")
    rs = add("restauration", cmd_restauration, "restaure les dernières sauvegardes dans un environnement Docker isolé et compare les totaux (CLD-15)")
    rs.add_argument("--postgres", metavar="FICHIER", help="nom d'un fichier .dump de backups/postgres (le dernier par défaut)")
    rs.add_argument("--mongo", metavar="FICHIER", help="nom d'un fichier .archive.gz de backups/mongo (le dernier par défaut)")
    rs.add_argument("--controles-negatifs", action="store_true", help="prouve ensuite que la vérification échoue sur un fichier altéré et sur un total faux")
    sp = add("sauvegarde-planifier", cmd_sauvegarde_planifier, "planifie la sauvegarde sans cron : attend le créneau, rattrape un oubli (CLD-15)")
    sp.add_argument("--heure", default="02:00", metavar="HH:MM", help="heure du poste (02:00 par défaut)")
    sp.add_argument("--toutes-les", type=int, metavar="SECONDES", help="essai : une sauvegarde toutes les N secondes au lieu d'une par jour")
    sp.add_argument("--executions", type=int, help="s'arrête après ce nombre de sauvegardes (essai)")
    sp.add_argument("--sans-rattrapage", action="store_true", help="n'attend que le créneau, même si la dernière sauvegarde a plus de 24 h")
    sp.add_argument("--verifier", action="store_true", help="après chaque sauvegarde, la restaure dans l'environnement isolé et compare les totaux")
    ob = add("observatoire", cmd_observatoire, "interface graphique des pannes : arrêter un service, voir l'alarme, le journal et la cause (CLD-14)")
    ob.add_argument("--port", type=int, default=8090, help="port local de l'interface (8090 par défaut)")
    pa = add("panne", cmd_panne, "arrête un service, détecte la panne par l'alarme, retrace le journal et la cause, rétablit (CLD-14)")
    pa.add_argument("service", help="service à arrêter (voir ops/alarmes.json), par exemple traitement ou collecte")
    pa.add_argument("--trafic", action="store_true", help="lance le simulateur vers la collecte pendant l'essai (le tableau a alors du débit à montrer)")
    pa.add_argument("--mode", choices=["stop", "pause"], default="stop", help="stop : arrêt du conteneur ; pause : service gelé, vivant mais muet")
    pa.add_argument("--duree", type=int, default=70, help="secondes de panne avant le rétablissement (70 par défaut : laisse le journal de la passerelle montrer ses erreurs)")
    pc = add("parcours", cmd_parcours, "rejoue le parcours de bout en bout et les cas d'échec sur la pile locale (CLD-13, la pile doit tourner)")
    pc.add_argument("cas", nargs="*", help="cas à jouer (N1 à N6, E1 à E3) ; tous par défaut")
    fc = add("flux-complet", cmd_flux_complet, "rejoue le flux complet (capteur simulé, collecte, traitement, alerte, recommandation, commande de feux) et les cas d'échec (MS-15, la pile doit tourner)")
    fc.add_argument("cas", nargs="*", help="cas à jouer (N1 à N7, F1 à F6) ; tous par défaut (environ 10 minutes)")
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
