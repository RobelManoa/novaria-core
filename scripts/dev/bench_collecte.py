#!/usr/bin/env python3
"""Mesure du débit maximal du service de collecte sur un poste (MS-08, ADR-001) : bibliothèque standard seulement.

Envoie des mesures valides distinctes à `POST /api/v1/measurements`, avec 1, 4, 16, 32 puis 64 connexions
simultanées (HTTP persistant), et rend, pour chaque palier : messages par seconde, latence (médiane, p95, p99, max)
et réponses obtenues. Puis rejoue les mêmes messages (tous doublons), puis envoie des messages invalides (tous rejetés).
Avec --container, l'utilisation du processeur du conteneur est échantillonnée (`docker stats`) pendant la mesure.

    python3 scripts/dev/bench_collecte.py --url http://127.0.0.1:8001 --messages 3000
    py -3 scripts/dev/bench_collecte.py --url http://127.0.0.1:8001 --container novaria-collecte-1

Chaque palier utilise un identifiant d'exécution neuf : aucun message n'est un doublon d'un autre palier. Code de sortie :
0 si toutes les réponses attendues sont arrivées (aucune erreur, aucun statut inattendu), 1 sinon, 2 pour une saisie erronée.
La mesure borne par le bas le débit du service : le client est un programme Python à fils d'exécution, il peut être
le premier à saturer. Elle dépend du poste (processeur, Docker Desktop) : à donner avec la machine.
"""

import argparse
import http.client
import json
import secrets
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import UTC, datetime, timedelta

DEFAULT_LEVELS = (1, 4, 16, 32, 64)
START = datetime(2026, 10, 20, 8, 0, 10, tzinfo=UTC)


def measurement(run_id: str, index: int) -> dict:
    """Une mesure conforme (MS-03) : 24 capteurs du réseau fixe, 4 par carrefour, un intervalle de 10 s chacun."""
    sensor = index % 24 + 1
    moment = START + timedelta(seconds=10 * (index // 24))
    return {
        "id": f"{run_id}:SENSOR_{sensor:03d}:{int(moment.timestamp() * 1000)}",
        "source": f"banc/{run_id}",
        "type": "novaria.iot.measurement.v1",
        "time": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "subject": f"INT_{(sensor - 1) // 4 + 1:02d}",
        "schema_version": "1.0",
        "correlation_id": f"corr-{int(moment.timestamp() * 1000)}",
        "domain": "iot",
        "data": {
            "sensor_id": f"SENSOR_{sensor:03d}",
            "road_segment_id": f"ROAD_{sensor:03d}",
            "intersection_id": f"INT_{(sensor - 1) // 4 + 1:02d}",
            "interval_s": 10,
            "vehicle_count": 4,
            "average_speed_kmh": 38.5,
            "occupancy_rate": 0.31,
            "queue_length_m": 22.0,
            "quality": {"status": "VALID"},
            "provenance": {"source_type": "SIMULATED", "run_id": run_id, "scenario_id": "banc", "seed": 1},
        },
    }


def invalid(run_id: str, index: int) -> dict:
    broken = measurement(run_id, index)
    broken["data"]["occupancy_rate"] = 1.7
    return broken


class Worker(threading.Thread):
    """Un fil, une connexion persistante : envoie les messages qu'on lui donne et note statut et durée."""

    def __init__(self, parts: urllib.parse.SplitResult, bodies: list[bytes]) -> None:
        super().__init__(daemon=True)
        self.parts, self.bodies = parts, bodies
        self.results: list[tuple[float, int, str]] = []
        self.errors = 0

    def run(self) -> None:
        connection = http.client.HTTPConnection(self.parts.hostname, self.parts.port, timeout=30)
        headers = {"Content-Type": "application/json"}
        for body in self.bodies:
            started = time.perf_counter()
            try:
                connection.request("POST", "/api/v1/measurements", body=body, headers=headers)
                response = connection.getresponse()
                payload = response.read()
                status = response.status
                decoded = json.loads(payload)
                # Un accusé porte `status` (ACCEPTED, DUPLICATE) ; une erreur `Problem` porte `code` (son `status` est numérique).
                outcome = decoded.get("code") or decoded.get("status") or "?"
            except (OSError, http.client.HTTPException, ValueError):
                self.errors += 1
                connection.close()
                connection = http.client.HTTPConnection(self.parts.hostname, self.parts.port, timeout=30)
                continue
            self.results.append((time.perf_counter() - started, status, str(outcome)))
        connection.close()


def percentile(sorted_values: list[float], fraction: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(fraction * len(sorted_values)))]


def run_level(url: str, bodies: list[bytes], concurrency: int, container: str | None, sample_every: float = 1.0) -> dict:
    parts = urllib.parse.urlsplit(url)
    workers = [Worker(parts, bodies[i::concurrency]) for i in range(concurrency)]
    cpu: list[float] = []
    sampler_stop = threading.Event()

    def sample() -> None:
        while not sampler_stop.wait(sample_every):
            done = subprocess.run(  # noqa: S603 - docker du poste, nom de conteneur donné par l'utilisateur
                ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}", container],
                capture_output=True, text=True, check=False,
            )  # fmt: skip
            try:
                cpu.append(float(done.stdout.strip().rstrip("%")))
            except ValueError:
                pass

    sampler = threading.Thread(target=sample, daemon=True) if container else None
    if sampler:
        sampler.start()
    started = time.perf_counter()
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    elapsed = time.perf_counter() - started
    sampler_stop.set()
    results = [r for worker in workers for r in worker.results]
    latencies = sorted(r[0] * 1000 for r in results)
    answers: dict[str, int] = {}
    for _, status, outcome in results:
        key = f"{status} {outcome}"
        answers[key] = answers.get(key, 0) + 1
    return {
        "concurrency": concurrency,
        "messages": len(bodies),
        "seconds": round(elapsed, 2),
        "per_second": round(len(results) / elapsed, 1),
        "p50_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_ms": round(percentile(latencies, 0.95), 1) if latencies else None,
        "p99_ms": round(percentile(latencies, 0.99), 1) if latencies else None,
        "max_ms": round(latencies[-1], 1) if latencies else None,
        "answers": answers,
        "transport_errors": sum(w.errors for w in workers),
        "cpu_max_percent": max(cpu) if cpu else None,
    }


def encode(events: list[dict]) -> list[bytes]:
    return [json.dumps(e, separators=(",", ":")).encode() for e in events]


def show(title: str, row: dict) -> None:
    cpu = f"  UC max {row['cpu_max_percent']:.0f} %" if row["cpu_max_percent"] is not None else ""
    print(
        f"  {title:<26} {row['per_second']:>8.1f} msg/s   médiane {row['p50_ms']:>6} ms   p95 {row['p95_ms']:>6} ms"
        f"   p99 {row['p99_ms']:>6} ms   max {row['max_ms']:>7} ms{cpu}   {row['answers']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8001", help="adresse de la collecte (8001 par défaut)")
    parser.add_argument("--messages", type=int, default=3000, help="messages par palier (3000)")
    parser.add_argument("--levels", default=",".join(map(str, DEFAULT_LEVELS)), help="connexions simultanées, séparées par des virgules")
    parser.add_argument("--container", help="nom du conteneur de la collecte : échantillonne son processeur (docker stats)")
    parser.add_argument("--json", action="store_true", help="écrit aussi le résultat en JSON sur la sortie standard")
    args = parser.parse_args(argv)
    try:
        levels = [int(x) for x in args.levels.split(",")]
        if args.messages < max(levels) or min(levels) < 1:
            raise ValueError
    except ValueError:
        print("ERREUR : --levels : entiers positifs, et --messages au moins égal au plus grand palier.", file=sys.stderr)
        return 2

    health = urllib.parse.urlsplit(args.url)
    try:
        probe = http.client.HTTPConnection(health.hostname, health.port, timeout=5)
        probe.request("GET", "/api/v1/health")
        reponse = probe.getresponse()
        reponse.read()
        probe.close()
        if reponse.status != 200:
            raise OSError
    except OSError:
        print(f"ERREUR : la collecte ne répond pas sur {args.url} (python3 scripts/dev/dev.py up).", file=sys.stderr)
        return 2

    unexpected = 0
    table: list[dict] = []
    print(f"Collecte : {args.url}, {args.messages} messages valides distincts par palier")
    last_run_id, last_bodies = "", []
    for level in levels:
        run_id = f"banc-{secrets.token_hex(4)}"
        bodies = encode([measurement(run_id, i) for i in range(args.messages)])
        row = run_level(args.url, bodies, level, args.container)
        show(f"{level} connexion(s)", row)
        unexpected += row["transport_errors"] + sum(n for k, n in row["answers"].items() if k != "202 ACCEPTED")
        table.append({"kind": "valides", **row})
        last_run_id, last_bodies = run_id, bodies
    best = max(table, key=lambda r: r["per_second"])
    print(f"Débit maximal mesuré : {best['per_second']} msg/s à {best['concurrency']} connexion(s).")

    duplicates = run_level(args.url, last_bodies, best["concurrency"], args.container)
    show("mêmes messages (doublons)", duplicates)
    unexpected += duplicates["transport_errors"] + sum(n for k, n in duplicates["answers"].items() if k != "202 DUPLICATE")
    table.append({"kind": "doublons", **duplicates})

    broken = encode([invalid(f"{last_run_id}-invalide", i) for i in range(args.messages)])
    rejected = run_level(args.url, broken, best["concurrency"], args.container)
    show("messages invalides", rejected)
    unexpected += rejected["transport_errors"] + sum(n for k, n in rejected["answers"].items() if k != "422 VALIDATION_ERROR")
    table.append({"kind": "invalides", **rejected})

    print(f"Réponses inattendues ou erreurs de transport : {unexpected}")
    if args.json:
        print(json.dumps(table, ensure_ascii=False))
    return 0 if unexpected == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
