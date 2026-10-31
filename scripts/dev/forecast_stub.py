"""MAQUETTE locale de GET /api/v1/forecasts, pour essayer la page des prévisions (FE-05). Ce n'est pas un service du produit.

L'API de traitement n'implémente pas encore cette route (issue IA-06). Cette maquette se place devant elle :
- tout ce qui n'est pas /api/v1/forecasts est transmis tel quel à l'API (connexion, indicateurs) ;
- /api/v1/forecasts est servie ici, conformément à contracts/openapi/traitement.openapi.yaml, par PERSISTANCE : la
  prévision d'un tronçon est son dernier ratio de vitesse connu à l'instant d'émission (`model.kind` = REFERENCE).

Pour que la page ait quelque chose à comparer sur un jeu de démonstration qui s'arrête dans le passé, l'émission est
décalée de `--back-minutes` minutes avant la fin des données : la prévision est alors comparée à ce qui a ensuite
été observé. Le nom du modèle dit « maquette » et la réponse porte l'en-tête X-Novaria-Maquette.

    python3 scripts/dev/dev.py forecast-stub          # écoute sur 127.0.0.1:8001, API sur 127.0.0.1:8000

Bibliothèque standard seule. Aucun jeton n'est conservé : celui de l'appelant est transmis à l'API, le temps de la requête.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORECASTS_PATH = "/api/v1/forecasts"
WINDOW_SIZES = (60, 300)
DEFAULT_HORIZON = 15
MODEL = {"kind": "REFERENCE", "name": "persistance (maquette locale)", "version": "maquette-0", "run_id": None}
FORWARDED_HEADERS = ("Authorization", "Content-Type", "Accept", "X-Correlation-ID")


class UpstreamError(Exception):
    """L'API a répondu par une erreur : son statut et son corps sont transmis tels quels."""

    def __init__(self, status: int, body: bytes, content_type: str):
        super().__init__(status)
        self.status, self.body, self.content_type = status, body, content_type


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def window_end(row: dict) -> datetime:
    return parse_time(row["window_start"]) + timedelta(seconds=row["window_size_s"])


def last_known_per_segment(fetch, back_minutes: int) -> tuple[datetime, list[dict]]:
    """Dernier indicateur de chaque tronçon à l'instant d'émission, et cet instant (rien si les données manquent)."""
    for size in WINDOW_SIZES:
        newest = fetch({"window_size_s": str(size), "limit": "1"})["items"]
        if not newest:
            continue
        issued = window_end(newest[0]) - timedelta(minutes=back_minutes)
        rows = fetch({
            "window_size_s": str(size), "run_id": newest[0]["provenance"]["run_id"], "limit": "500",
            "from": iso(issued - timedelta(minutes=4 * size // 60)), "to": iso(issued),
        })["items"]
        latest: dict[str, dict] = {}
        for row in rows:  # du plus récent au plus ancien : le premier vu de chaque tronçon est son dernier
            if window_end(row) <= issued and row["speed_ratio"] is not None:
                latest.setdefault(row["road_segment_id"], row)
        return issued, [latest[key] for key in sorted(latest)]
    return datetime.now(UTC), []


def forecast_for(row: dict, issued: datetime, horizon_min: int) -> dict:
    return {
        "road_segment_id": row["road_segment_id"],
        "issued_at": iso(issued),
        "horizon_min": horizon_min,
        "target_time": iso(issued + timedelta(minutes=horizon_min)),
        "predicted_speed_ratio": row["speed_ratio"],
        "predicted_state": row["congestion_state"],
        "model": MODEL,
        "provenance": row["provenance"],
    }


def build_forecasts(fetch, query: dict[str, list[str]], back_minutes: int) -> dict:
    horizon = int(query.get("horizon_min", [DEFAULT_HORIZON])[0])
    wanted = set(query.get("road_segment_id", []))
    issued, rows = last_known_per_segment(fetch, back_minutes)
    return {"items": [forecast_for(row, issued, horizon) for row in rows if not wanted or row["road_segment_id"] in wanted]}


def make_handler(upstream: str, back_minutes: int):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _call_upstream(self, path: str, body: bytes | None = None) -> tuple[int, bytes, str]:
            headers = {name: self.headers[name] for name in FORWARDED_HEADERS if self.headers.get(name)}
            request = urllib.request.Request(upstream + path, data=body, headers=headers, method=self.command)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 : adresse http(s) vérifiée au démarrage
                    return response.status, response.read(), response.headers.get("Content-Type", "application/json")
            except urllib.error.HTTPError as error:
                return error.code, error.read(), error.headers.get("Content-Type", "application/json")

        def _handle(self):
            parsed = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            if self.command == "GET" and parsed.path == FORECASTS_PATH:
                def fetch(query: dict[str, str]) -> dict:
                    status, payload, content_type = self._call_upstream(f"/api/v1/indicators?{urllib.parse.urlencode(query)}")
                    if status != 200:
                        raise UpstreamError(status, payload, content_type)
                    return json.loads(payload)

                try:
                    answer = build_forecasts(fetch, urllib.parse.parse_qs(parsed.query), back_minutes)
                except UpstreamError as error:
                    return self._send(error.status, error.body, error.content_type)
                return self._send(200, json.dumps(answer).encode(), "application/json", {"X-Novaria-Maquette": "forecasts"})
            try:
                status, payload, content_type = self._call_upstream(self.path, body)
            except urllib.error.URLError:
                problem = {"type": "about:blank", "title": "API injoignable", "status": 502, "code": "UPSTREAM_UNAVAILABLE"}
                return self._send(502, json.dumps(problem).encode(), "application/problem+json")
            self._send(status, payload, content_type)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

        def log_message(self, format, *args):  # noqa: A002 : signature imposée ; ni en-têtes ni jetons dans les journaux
            sys.stderr.write(f"maquette {self.command} {urllib.parse.urlsplit(self.path).path} -> {args[1] if len(args) > 1 else ''}\n")

    return Handler


def make_server(upstream: str, port: int, back_minutes: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    if not upstream.startswith(("http://", "https://")):
        raise ValueError("L'adresse de l'API doit commencer par http:// ou https://")
    return ThreadingHTTPServer((host, port), make_handler(upstream.rstrip("/"), back_minutes))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream", default="http://127.0.0.1:8000", help="API de traitement")
    parser.add_argument("--port", type=int, default=8001, help="port d'écoute (127.0.0.1)")
    parser.add_argument("--back-minutes", type=int, default=60, help="émission décalée avant la fin des données (0 : au plus près)")
    options = parser.parse_args(argv)
    try:
        server = make_server(options.upstream, options.port, options.back_minutes)
    except (ValueError, OSError) as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        return 1
    print(f"MAQUETTE de /api/v1/forecasts : http://127.0.0.1:{options.port}  (API : {options.upstream} ; émission {options.back_minutes} min avant la fin des données ; Ctrl+C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
