"""Service HTTP du simulateur (conteneur Compose) : sonde de santé, lancement d'un run, anomalies à la demande.

Inchangé depuis la première version du simulateur (MS-06) : `GET /api/v1/health` (même contenu que les services) et 404 ailleurs. Nouveau :

    GET    /api/v1/scenarios   les scénarios
    GET    /api/v1/run         état du run en cours ou du dernier
    POST   /api/v1/run         démarre un run : {"scenario", "seed", "rate", "sink", "run_id", "start", "duration"}
    DELETE /api/v1/run         l'arrête
    POST   /api/v1/anomalies   injecte une anomalie dans le run en cours, au prochain intervalle (« à la demande »)

Un seul run à la fois. Aucun run ne démarre tout seul : la collecte n'a pas encore son point d'entrée (MS-05).
"""

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .anomalies import Anomaly, AnomalyError, parse_duration, parse_utc
from .pacing import Pacer
from .run import Run, default_config
from .runner import Stats, execute
from .scenarios import SCENARIOS
from .sinks import CollecteSink, RunDirectory

HEALTH_PATH = "/api/v1/health"
MAX_BODY = 64 * 1024
# Bornes d'un run demandé par HTTP (la ligne de commande, elle, n'en a pas : un jeu d'entraînement peut durer des semaines)
MAX_DURATION_S = 7 * 24 * 3600
MAX_RATE = 1_000_000.0
MAX_ANOMALIES_AT_START = 100
_QUERY = re.compile(r'\?[^\s"]*')


def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": __version__,
        "revision": os.environ.get("GIT_SHA", "dev"),
        "environment": os.environ.get("ENVIRONMENT", "local"),
    }


class RequestError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class Controller:
    """Le run en cours (un seul) et son thread."""

    def __init__(self, collecte_url: str | None = None, out_dir: str | None = None):
        self.collecte_url = collecte_url if collecte_url is not None else os.environ.get("COLLECTE_URL")
        self.out_dir = out_dir or os.environ.get("SIMULATOR_OUT_DIR", "/tmp/simulateur")  # noqa: S108 : dossier d'essai du conteneur
        self._lock = threading.Lock()
        self._run: Run | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._stats = Stats()
        self._state = "idle"
        self._sink: CollecteSink | None = None
        self._error: str | None = None
        self._rate: float | None = None

    def status(self) -> dict:
        with self._lock:
            run = self._run
            body: dict = {"state": self._state}
            if run is not None:
                body.update(
                    run_id=run.config.run_id, scenario_id=run.config.scenario_id, seed=run.config.seed, rate=self._rate,
                    intervals_done=run.processed, intervals_total=run.config.interval_count,
                    delivered=self._stats.delivered, anomalies=[a.to_json() for a in run.anomalies],
                )
                if self._sink is not None:
                    body["collecte"] = vars(self._sink.receipts)
            if self._error:
                body["error"] = self._error
            return body

    def start(self, params: dict) -> dict:
        with self._lock:
            if self._state == "running":
                raise RequestError(409, "un run est déjà en cours : l'arrêter d'abord (DELETE /api/v1/run)")
        try:
            run = self._build_run(params)
            rate = _rate(params.get("rate", 0))
            sink_name = params.get("sink") or ("collecte" if self.collecte_url else "aucun")
            sinks, directory, collecte = self._sinks(sink_name, run)
        except (AnomalyError, ValueError, TypeError) as error:
            raise RequestError(400, str(error)) from error
        with self._lock:
            self._run, self._sink, self._rate, self._error = run, collecte, rate, None
            self._stats, self._state = Stats(), "running"
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._work, args=(run, sinks, directory, rate), daemon=True)
            self._thread.start()
        return self.status()

    def _build_run(self, params: dict) -> Run:
        scenario_id = params.get("scenario")
        if scenario_id not in SCENARIOS:
            raise ValueError(f"scénario inconnu : {scenario_id!r} (attendus : {', '.join(SCENARIOS)})")
        scenario = SCENARIOS[scenario_id]
        start = parse_utc(params["start"]) if params.get("start") else None
        first = start or scenario.default_start()
        duration = parse_duration(params["duration"]) if params.get("duration") is not None else None
        if duration is not None and duration > MAX_DURATION_S:
            raise ValueError(f"durée : {MAX_DURATION_S // 86400} jours au plus par le service")
        items = params.get("anomalies", [])
        if not isinstance(items, list) or len(items) > MAX_ANOMALIES_AT_START:
            raise ValueError(f"anomalies : une liste de {MAX_ANOMALIES_AT_START} au plus (les suivantes s'injectent pendant le run)")
        anomalies = tuple(Anomaly.from_json(item, first) for item in items)
        seed = params.get("seed", 42)
        return Run(default_config(scenario_id, seed, params.get("run_id"), start, None, duration, anomalies))

    def _sinks(self, name: str, run: Run):
        if name == "collecte":
            if not self.collecte_url:
                raise ValueError("COLLECTE_URL est absente : impossible d'envoyer à la collecte")
            sink = CollecteSink(self.collecte_url)
            return [sink], None, sink
        if name == "fichier":
            base = Path(self.out_dir).resolve()
            target = (base / run.config.run_id).resolve()
            if target == base or not target.is_relative_to(base):  # défense en profondeur : le motif du run_id l'interdit déjà
                raise ValueError("run_id : chemin hors du dossier de sortie")
            directory = RunDirectory(target)
            return [directory.messages], directory, None
        if name == "aucun":
            return [], None, None
        raise ValueError(f"destination inconnue : {name!r} (collecte, fichier ou aucun)")

    def _work(self, run: Run, sinks, directory, rate) -> None:
        truth = directory.truth if directory else None
        try:
            stats = execute(run, sinks, truth, Pacer(rate), self._stop, self._stats)
            if directory:
                directory.close(run)
            final = "stopped" if stats.stopped else "finished"
        except Exception as error:  # noqa: BLE001 : le thread ne doit pas mourir sans le dire
            self._error, final = f"{type(error).__name__}: {error}", "error"
        finally:
            for sink in sinks:
                sink.close()
        with self._lock:
            self._state = final

    def stop(self) -> dict:
        with self._lock:
            thread = self._thread
            if self._state != "running" or thread is None:
                raise RequestError(409, "aucun run en cours")
        self._stop.set()
        thread.join(timeout=10)
        return self.status()

    def inject(self, body: dict) -> dict:
        with self._lock:
            run = self._run if self._state == "running" else None
        if run is None:
            raise RequestError(409, "aucun run en cours : démarrer un run d'abord (POST /api/v1/run)")
        try:
            anomaly = run.add_anomaly(Anomaly.from_json(body, run.config.start))
        except (AnomalyError, ValueError, TypeError) as error:
            raise RequestError(400, str(error)) from error
        return {"anomaly": anomaly.to_json(), "anomaly_id": anomaly.anomaly_id}


def _rate(value) -> float:
    if value == "realtime":
        return 2.4
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= MAX_RATE:
        raise ValueError(f"rate : nombre de messages par seconde, de 0 (sans frein) à {int(MAX_RATE)}, ou \"realtime\"")
    return float(value)


def make_handler(controller: Controller):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise RequestError(413, "corps trop grand")
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError as error:
                raise RequestError(400, "JSON invalide") from error
            if not isinstance(body, dict):
                raise RequestError(400, "un objet JSON est attendu")
            return body

        def _route(self, method: str) -> None:
            routes = {
                ("GET", HEALTH_PATH): lambda: (200, health()),
                ("GET", "/api/v1/scenarios"): lambda: (200, {"scenarios": [
                    {"scenario_id": s.scenario_id, "description": s.description, "start": s.start, "duration_s": s.duration_s}
                    for s in SCENARIOS.values()]}),
                ("GET", "/api/v1/run"): lambda: (200, controller.status()),
                ("POST", "/api/v1/run"): lambda: (202, controller.start(self._json_body())),
                ("DELETE", "/api/v1/run"): lambda: (200, controller.stop()),
                ("POST", "/api/v1/anomalies"): lambda: (202, controller.inject(self._json_body())),
            }
            path = self.path.split("?")[0]
            try:
                handler = routes.get((method, path))
                if handler is None:
                    known = any(p == path for _, p in routes)
                    raise RequestError(405 if known else 404, "méthode non permise" if known else "introuvable")
                status, body = handler()
            except RequestError as error:
                status, body = error.status, {"detail": error.detail}
            self._send(status, body)

        def do_GET(self) -> None:  # noqa: N802 : noms imposés par http.server
            self._route("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._route("POST")

        def do_DELETE(self) -> None:  # noqa: N802
            self._route("DELETE")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            # Jamais la query string : un jeton collé dans l'adresse n'a rien à faire dans un journal (même règle que le
            # service traitement, docs/04-devsecops/securite-applicative.md). Le corps d'une requête n'est jamais écrit.
            print(json.dumps({"service": "simulateur", "message": _QUERY.sub("", format % args)}), flush=True)

    return Handler


def make_server(port: int = 8000, host: str = "0.0.0.0",  # noqa: S104 : écoute dans le conteneur
                controller: Controller | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(controller or Controller()))


def serve(port: int) -> int:
    make_server(port).serve_forever()
    return 0
