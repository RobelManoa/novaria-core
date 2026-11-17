"""Destinations des messages : dossier de run (pour IA-08), sortie standard, ou collecte par HTTP."""

import hashlib
import http.client
import json
import re
import socket
import sys
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .events import to_line
from .network import INTERVAL_S, SENSOR_IDS
from .resilience import CircuitBreaker, CircuitOpen, retry
from .run import Delivery, Run

MEASUREMENTS_FILE = "mesures.jsonl"
TRUTH_FILE = "verite-terrain.jsonl"
MANIFEST_FILE = "manifest.json"
INGEST_PATH = "/api/v1/measurements"
CORRELATION_HEADER = "X-Correlation-ID"
SOBER_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")  # ce que la collecte reprend dans ses journaux


class Unavailable(Exception):
    """La collecte répond 503 : une dépendance (bus, base) est tombée ; rien n'a été perdu, on renvoie."""


class JsonlFile:
    """Fichier JSONL écrit par l'outil lui-même : UTF-8, fins de ligne LF, empreinte SHA-256 calculée à l'écriture."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("w", encoding="utf-8", newline="\n")
        self._hash = hashlib.sha256()
        self.lines = 0

    def write(self, document: dict) -> None:
        line = to_line(document) + "\n"
        self._file.write(line)
        self._hash.update(line.encode("utf-8"))
        self.lines += 1

    def close(self) -> None:
        self._file.close()

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()


class FileSink:
    def __init__(self, path: Path):
        self.file = JsonlFile(path)

    def send(self, delivery: Delivery) -> None:
        self.file.write(delivery.event)

    def close(self) -> None:
        self.file.close()


class StdoutSink:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout

    def send(self, delivery: Delivery) -> None:
        self.stream.write(to_line(delivery.event) + "\n")

    def close(self) -> None:
        self.stream.flush()


@dataclass
class Receipts:
    accepted: int = 0
    duplicates: int = 0
    rejected: int = 0
    errors: int = 0
    last_error: str | None = None


@dataclass
class CollecteSink:
    """POST de chaque message sur `/api/v1/measurements` : 202 ACCEPTED, 202 DUPLICATE (même id), 422 hors contrat.

    MS-16 : délai d'attente borné (`timeout_s`), reprises avec attente croissante (`attempts` essais, attente
    `retry_base_s` puis doublée, plafonnée à `retry_max_s`) sur une connexion tombée ou un 503, et un disjoncteur : après
    `circuit_failures` envois en échec de suite, les messages suivants échouent aussitôt (comptés dans `receipts.errors`)
    pendant `circuit_reset_s`, puis un essai part. Chaque requête porte l'identifiant de corrélation du message
    (`X-Correlation-ID`) : la collecte l'écrit dans son journal, le flux le reprend.
    """

    base_url: str
    timeout_s: float = 5.0
    receipts: Receipts = field(default_factory=Receipts)
    attempts: int = 3
    retry_base_s: float = 0.1
    retry_max_s: float = 1.0
    circuit_failures: int = 5
    circuit_reset_s: float = 10.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    retries: int = 0
    circuit_opened: int = 0
    _connection: http.client.HTTPConnection | None = None

    def __post_init__(self) -> None:
        parts = urllib.parse.urlsplit(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("l'adresse de la collecte doit commencer par http:// ou https://")
        self._parts = parts
        self._failures = (OSError, http.client.HTTPException, Unavailable)
        self.breaker = CircuitBreaker(
            "collecte", failure_threshold=self.circuit_failures, reset_timeout_s=self.circuit_reset_s,
            trip_on=self._failures, clock=self.clock, observer=self._observe,
        )

    def _observe(self, event: str, **fields) -> None:
        if event == "retry":
            self.retries += 1
        elif event == "state" and fields["after"] == "open":
            self.circuit_opened += 1

    def _connect(self) -> http.client.HTTPConnection:
        if self._connection is None:
            connection_class = http.client.HTTPSConnection if self._parts.scheme == "https" else http.client.HTTPConnection
            connection = connection_class(self._parts.hostname, self._parts.port, timeout=self.timeout_s)
            connection.connect()
            # Petits messages envoyés à la suite : sans TCP_NODELAY, l'algorithme de Nagle et l'ACK retardé du serveur
            # coûtent ~40 ms par message, soit 25 messages par seconde au plus.
            connection.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._connection = connection
        return self._connection

    def _post(self, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        try:
            connection = self._connect()
            connection.request("POST", INGEST_PATH, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
        except (OSError, http.client.HTTPException):
            self.close()  # une connexion persistante tombée est refaite à l'essai suivant
            raise
        if response.status == 503:
            raise Unavailable("HTTP 503")
        return response.status, payload

    def send(self, delivery: Delivery) -> None:
        body = to_line(delivery.event).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        correlation = str(delivery.event.get("correlation_id", ""))
        if SOBER_ID.fullmatch(correlation):
            headers[CORRELATION_HEADER] = correlation
        try:
            status, payload = self.breaker.call(
                lambda: retry(
                    lambda: self._post(body, headers), attempts=self.attempts, base_s=self.retry_base_s,
                    max_s=self.retry_max_s, retry_on=self._failures, sleep=self.sleep, observer=self._observe,
                    name="collecte",
                )
            )
        except CircuitOpen:
            self.receipts.errors += 1
            self.receipts.last_error = "disjoncteur ouvert"
            return
        except self._failures as error:
            self.receipts.errors += 1
            self.receipts.last_error = type(error).__name__
            return
        self._count(status, payload)

    def _count(self, status: int, payload: bytes) -> None:
        if status == 202:
            try:
                state = json.loads(payload).get("status")
            except ValueError:
                state = None
            if state == "DUPLICATE":
                self.receipts.duplicates += 1
            else:
                self.receipts.accepted += 1
        elif status == 422:
            self.receipts.rejected += 1
        else:
            self.receipts.errors += 1
            self.receipts.last_error = f"HTTP {status}"

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class RunDirectory:
    """Un run complet sur disque : messages (dans l'ordre de livraison), vérité terrain à part, et manifeste."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.messages = FileSink(directory / MEASUREMENTS_FILE)
        self.truth = JsonlFile(directory / TRUTH_FILE)

    def close(self, run: Run) -> dict:
        self.messages.close()
        self.truth.close()
        manifest = manifest_for(run, {
            MEASUREMENTS_FILE: {"lines": self.messages.file.lines, "sha256": self.messages.file.sha256},
            TRUTH_FILE: {"lines": self.truth.lines, "sha256": self.truth.sha256},
        })
        (self.directory / MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return manifest


def manifest_for(run: Run, files: dict) -> dict:
    """Description du run, sans horloge : deux exécutions identiques écrivent un manifeste identique."""
    config = run.config
    return {
        "run_id": config.run_id,
        "provenance": {"source_type": "SIMULATED", "scenario_id": config.scenario_id, "seed": config.seed},
        "generator_version": __version__,
        "contract": "novaria.iot.measurement.v1, schema_version 1.0 (MS-03)",
        "start": config.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": config.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval_s": INTERVAL_S,
        "sensors": len(SENSOR_IDS),
        "intervals": config.interval_count,
        "intervals_played": run.processed,  # moins que `intervals` si le run a été arrêté : les anomalies de la fin ne sont pas jouées
        "anomalies": [anomaly.to_json() for anomaly in run.anomalies],
        "files": files,
        "note": "verite-terrain.jsonl garde l'état de congestion voulu (label_state) : il n'est jamais dans les messages.",
    }
