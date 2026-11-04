"""Ligne de commande : `run` (fichier, sortie standard ou collecte), `scenarios`. Les messages seuls vont sur la sortie
standard avec `--stdout` ; le résumé et les erreurs vont sur la sortie d'erreur."""

import argparse
import json
import sys
from pathlib import Path

from .anomalies import Anomaly, AnomalyError, parse_duration, parse_spec, parse_utc
from .network import SENSOR_IDS
from .pacing import Pacer
from .run import Run, default_config
from .runner import Stats, execute
from .scenarios import SCENARIOS
from .sinks import CollecteSink, JsonlFile, RunDirectory, StdoutSink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simulator/app.py", description="Simulateur de capteurs IoT du trafic routier (MS-07).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scenarios", help="liste les scénarios")
    serve = sub.add_parser("serve", help="démarre le service HTTP (sonde de santé, lancement de runs, anomalies à la demande)")
    serve.add_argument("--port", type=int, default=8000)
    run = sub.add_parser("run", help="rejoue un scénario avec une graine : mêmes messages à chaque fois")
    run.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    run.add_argument("--seed", type=int, default=42, help="graine (défaut 42) : même graine, mêmes messages")
    run.add_argument("--run-id", help="identifiant du run (défaut : run-<scénario>-<graine>)")
    run.add_argument("--start", help="début, UTC (défaut : celui du scénario), ex. 2026-10-20T06:00:00Z")
    run.add_argument("--end", help="fin, UTC (exclusive avec --duration)")
    run.add_argument("--duration", help="durée (90, 90s, 30m, 3h) ; défaut : celle du scénario")
    run.add_argument("--anomaly", action="append", default=[], metavar="SPEC",
                     help="anomalie programmée, répétable : muet:sensor=SENSOR_007,at=+600,duration=5m (voir le README)")
    run.add_argument("--anomalies-file", type=Path, help="fichier JSON : liste d'anomalies (celles du manifeste d'un run)")
    run.add_argument("--out", type=Path, help="dossier du run : messages, vérité terrain, manifeste")
    run.add_argument("--stdout", action="store_true", help="écrit les messages sur la sortie standard (JSON, un par ligne)")
    run.add_argument("--collecte-url", help="envoie chaque message à POST <url>/api/v1/measurements")
    run.add_argument("--truth", type=Path, help="fichier de vérité terrain (avec --stdout ou --collecte-url ; avec --out, il est dans le dossier)")
    run.add_argument("--rate", default="0", help="messages par seconde (0 : sans frein), ou « realtime » (24 capteurs toutes les 10 s)")
    return parser


def parse_rate(text: str) -> float:
    if text == "realtime":
        return len(SENSOR_IDS) / 10
    try:
        rate = float(text)
    except ValueError as error:
        raise ValueError(f"débit illisible : {text!r} (nombre de messages par seconde, ou realtime)") from error
    if rate < 0:
        raise ValueError("le débit ne peut pas être négatif")
    return rate


def load_run(args) -> Run:
    start = parse_utc(args.start) if args.start else None
    end = parse_utc(args.end) if args.end else None
    if end and args.duration:
        raise ValueError("--end et --duration s'excluent")
    scenario = SCENARIOS[args.scenario]
    first = start or scenario.default_start()
    anomalies: list[Anomaly] = [parse_spec(spec, first) for spec in args.anomaly]
    if args.anomalies_file:
        try:
            documents = json.loads(args.anomalies_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"fichier d'anomalies illisible : {error}") from error
        if not isinstance(documents, list):
            raise ValueError("le fichier d'anomalies contient une liste JSON")
        anomalies.extend(Anomaly.from_json(document, first) for document in documents)
    duration = parse_duration(args.duration) if args.duration else None
    config = default_config(args.scenario, args.seed, args.run_id, start, end, duration, tuple(anomalies))
    return Run(config)


def run_command(args) -> int:
    if not (args.out or args.stdout or args.collecte_url):
        raise ValueError("choisir une destination : --out, --stdout ou --collecte-url")
    run = load_run(args)
    pacer = Pacer(parse_rate(args.rate))
    directory = RunDirectory(args.out) if args.out else None
    truth = directory.truth if directory else (JsonlFile(args.truth) if args.truth else None)
    sinks = [directory.messages] if directory else []
    if args.stdout:
        sinks.append(StdoutSink())
    collecte = CollecteSink(args.collecte_url) if args.collecte_url else None
    if collecte:
        sinks.append(collecte)
    try:
        stats: Stats = execute(run, sinks, truth, pacer)
    finally:
        for sink in sinks:
            sink.close()
    manifest = directory.close(run) if directory else None
    if truth is not None and not directory:
        truth.close()
    summary = {"run_id": run.config.run_id, "messages": stats.delivered, "truth_rows": stats.truth_rows}
    if collecte:
        summary["collecte"] = vars(collecte.receipts)
    if manifest:
        summary["sha256"] = {name: info["sha256"] for name, info in manifest["files"].items()}
        summary["out"] = str(args.out)
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    return 1 if collecte and collecte.receipts.errors else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scenarios":
            for scenario in SCENARIOS.values():
                print(f"{scenario.scenario_id:<20} {scenario.start} UTC, {scenario.duration_s // 3600} h  {scenario.description}")
            return 0
        if args.command == "serve":
            from .service import serve

            return serve(args.port)
        return run_command(args)
    except (AnomalyError, ValueError, OSError) as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        return 2

