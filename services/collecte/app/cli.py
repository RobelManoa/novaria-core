"""Rejeu d'un fichier de mesures par l'entrée « MQTT simulé » (MS-08).

    python -m app.cli replay-mqtt mesures.jsonl [--redeliver] [--limit N]

Chaque ligne du fichier (un message JSON, comme l'écrit le simulateur dans `mesures.jsonl`) est
livrée à l'abonné MQTT simulé, sur le sujet `novaria/iot/measurements/<capteur>`. Les connexions
sont celles du service : `KAFKA_BOOTSTRAP_SERVERS`, `MONGO_URL`, `MONGO_DB`. `--redeliver` livre
chaque message deux fois, comme le ferait une redélivrance MQTT de qualité de service 1 : la seconde
est un doublon.

Code de sortie : 0 si chaque message a une issue (acceptée, doublon ou rejetée), 1 si le bus ou la
base a manqué à au moins un message (à rejouer), 2 pour une erreur de saisie.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from app.adapters.mqtt_sim import TOPIC_PREFIX, SimulatedMqttAdapter
from app.api.deps import close_components, get_ingestion_service
from app.services.ingestion import PublishFailed, StoreFailed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay-mqtt", help="rejoue un fichier de mesures")
    replay.add_argument("file", type=Path, help="fichier JSON Lines : un message par ligne")
    replay.add_argument("--redeliver", action="store_true", help="livre chaque message deux fois")
    replay.add_argument("--limit", type=int, default=0, help="ne rejoue que les N premières lignes")
    return parser


def topic_of(line: bytes) -> str:
    """Le sujet MQTT d'un message : son capteur, ou `inconnu` si la ligne n'en dit pas."""
    try:
        sensor = json.loads(line)["data"]["sensor_id"]
    except (ValueError, KeyError, TypeError):
        sensor = None
    return TOPIC_PREFIX + (
        sensor if isinstance(sensor, str) and "/" not in sensor and sensor else "inconnu"
    )


def replay(path: Path, *, redeliver: bool, limit: int, adapter: SimulatedMqttAdapter) -> Counter:
    counts: Counter = Counter()
    with path.open("rb") as handle:
        for number, line in enumerate(handle, start=1):
            if limit and number > limit:
                break
            line = line.strip()
            if not line:
                continue
            for _ in range(2 if redeliver else 1):
                try:
                    receipt = adapter.on_message(topic_of(line), line)
                except (PublishFailed, StoreFailed):
                    counts["FAILED"] += 1
                    continue
                counts[receipt.outcome.value if receipt else "IGNORED"] += 1
    return counts


def main(argv: Sequence[str] | None = None, *, adapter: SimulatedMqttAdapter | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not arguments.file.is_file():
        print(f"ERREUR : fichier introuvable : {arguments.file}", file=sys.stderr)
        return 2
    try:
        counts = replay(
            arguments.file,
            redeliver=arguments.redeliver,
            limit=arguments.limit,
            adapter=adapter or SimulatedMqttAdapter(get_ingestion_service()),
        )
    finally:
        close_components()
    summary = ", ".join(
        f"{name}={counts[name]}" for name in ("ACCEPTED", "DUPLICATE", "REJECTED", "FAILED")
    )
    print(f"Rejeu terminé : {summary}")
    return 1 if counts["FAILED"] else 0


if __name__ == "__main__":
    sys.exit(main())
