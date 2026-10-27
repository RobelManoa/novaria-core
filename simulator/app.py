"""Simulateur de capteurs IoT : squelette de MS-06. La génération des mesures arrive avec MS-07.

Il démarre, répond à la sonde de santé `GET /api/v1/health` (même contenu que les services) et ne produit encore
aucune mesure. Bibliothèque standard seulement.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1.0"
HEALTH_PATH = "/api/v1/health"


def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": VERSION,
        "revision": os.environ.get("GIT_SHA", "dev"),
        "environment": os.environ.get("ENVIRONMENT", "local"),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 : nom imposé par http.server
        ok = self.path == HEALTH_PATH
        body = json.dumps(health() if ok else {"detail": "introuvable"}).encode("utf-8")
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(json.dumps({"service": "simulateur", "message": format % args}), flush=True)


def make_server(port: int = 8000, host: str = "0.0.0.0") -> ThreadingHTTPServer:  # noqa: S104
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    make_server(int(os.environ.get("PORT", "8000"))).serve_forever()
