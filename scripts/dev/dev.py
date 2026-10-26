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
from collections.abc import Sequence
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


# --------------------------------------------------------------------------- Kafka (ADR-009, LOC-04)
# Les outils en ligne de commande de Kafka sont dans le conteneur : aucun client Kafka à installer sur le poste.
KAFKA_BIN = "/opt/kafka/bin"
KAFKA_BOOTSTRAP = "localhost:9092"  # adresse vue depuis le conteneur du broker
KAFKA_PARTITIONS = 3  # ADR-009 §4.3 : 3 partitions par sujet en local
KAFKA_SEPARATOR = "|"  # sépare partition, décalage, clé et valeur à la relecture, clé et valeur à la publication
EXAMPLE_MEASUREMENT = ROOT / "contracts" / "events" / "examples" / "mesure-valide.json"
VALIDATOR = ROOT / "contracts" / "validate_events.py"


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
