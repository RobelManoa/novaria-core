"""MAQUETTE locale de GET /api/v1/reports, pour essayer la page des rapports (FE-06). Ce n'est pas un service du produit.

Le service de traitement n'implémente pas encore ces routes et le robot qui produit les rapports (IA-07) n'existe pas.
Cette maquette se place devant l'API :
- tout ce qui n'est pas /api/v1/reports est transmis tel quel à l'API (connexion, indicateurs) ;
- /api/v1/reports (liste paginée) et /api/v1/reports/{report_id}/content (PDF) sont servis ici, conformément à
  contracts/openapi/traitement.openapi.yaml (Proposition). Les rapports sont FICTIFS : un PDF d'une page, fabriqué
  à la volée, qui se dit « maquette » dans son titre et dans son contenu. Taille et empreinte SHA-256 de la liste
  sont celles des octets réellement servis.

Le jeton de l'appelant est contrôlé en le présentant à l'API (GET /api/v1/auth/me) : la maquette n'en garde aucun.

    python3 scripts/dev/dev.py report-stub            # écoute sur 127.0.0.1:8002, API sur 127.0.0.1:8000
    python3 scripts/dev/dev.py report-stub --count 0  # le robot n'a rien déposé : liste vide
    python3 scripts/dev/dev.py report-stub --count 45 # trois pages de 20 : « Afficher la suite »

Bibliothèque standard seule.
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPORTS_PATH = "/api/v1/reports"
CONTENT_PATH = re.compile(r"^/api/v1/reports/([^/]+)/content$")
CURRENT_USER_PATH = "/api/v1/auth/me"
FORWARDED_HEADERS = ("Authorization", "Content-Type", "Accept", "X-Correlation-ID")
DEFAULT_COUNT = 3
DEFAULT_LIMIT = 100  # défaut du paramètre `limit` du contrat
MAX_LIMIT = 500
# Fixe, pour que deux lancements rendent les mêmes rapports : le jour de référence est le dernier jour couvert.
LAST_DAY = datetime(2026, 11, 4, tzinfo=UTC)
NAMESPACE = uuid.UUID("5d3b7a3e-6c0e-4d53-9d0e-0f5a1a2b3c4d")
UUID_TEXT = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
CURSOR_TEXT = re.compile(r"^maquette-([0-9]{1,6})$")


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_pdf(lines: list[str]) -> bytes:
    """PDF d'une page, texte seul (Helvetica), avec une table des références exacte. ASCII uniquement."""

    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text = "BT /F1 12 Tf 56 780 Td 18 TL\n" + "\n".join(f"({escape(line)}) Tj T*" for line in lines) + "\nET"
    stream = text.encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_report(index: int) -> tuple[dict, bytes]:
    """Le rapport n° `index` (0 = le plus récent) : ses métadonnées et ses octets. Les deux concordent."""
    day = LAST_DAY - timedelta(days=index)
    end = day + timedelta(days=1)
    label = day.strftime("%d/%m/%Y")
    content = build_pdf([
        "MAQUETTE LOCALE - rapport fictif, ne provient pas du robot",
        f"Rapport de supervision du {day.strftime('%Y-%m-%d')}",
        f"Periode couverte : {iso(day)} -> {iso(end)}",
        "Ce fichier sert a essayer la page des rapports (FE-06).",
    ])
    metadata = {
        "report_id": str(uuid.uuid5(NAMESPACE, f"maquette-{index}")),
        "title": f"Rapport de supervision du {label} (maquette)",
        "period_start": iso(day),
        "period_end": iso(end),
        "generated_at": iso(end + timedelta(minutes=5)),
        "file_name": f"rapport-{day.strftime('%Y-%m-%d')}-maquette.pdf",
        "size_bytes": len(content),
        "content_type": "application/pdf",
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    return metadata, content


def problem(status: int, code: str, title: str, detail: str | None = None) -> dict:
    body = {"type": f"https://novaria.local/problems/{code.lower().replace('_', '-')}", "title": title, "status": status,
            "code": code, "correlation_id": str(uuid.uuid4())}
    if detail:
        body["detail"] = detail
    return body


def list_reports(count: int, query: dict[str, list[str]]) -> tuple[int, dict]:
    """Une page du contrat : `limit` (1 à 500, 100 par défaut) et `cursor` (position de la page, opaque pour l'appelant)."""
    try:
        limit = int(query.get("limit", [DEFAULT_LIMIT])[0])
    except ValueError:
        limit = 0
    if not 1 <= limit <= MAX_LIMIT:
        return 422, problem(422, "VALIDATION_ERROR", "Entrée invalide", "query.limit : la valeur doit être comprise entre 1 et 500.")
    start = 0
    if "cursor" in query:
        matched = CURSOR_TEXT.match(query["cursor"][0])
        if matched is None or int(matched.group(1)) > count:
            return 422, problem(422, "VALIDATION_ERROR", "Entrée invalide", "query.cursor : curseur inconnu.")
        start = int(matched.group(1))
    end = min(start + limit, count)
    items = [make_report(index)[0] for index in range(start, end)]
    return 200, {"items": items, "next_cursor": f"maquette-{end}" if end < count else None}


def find_report(count: int, report_id: str) -> tuple[int, dict | tuple[dict, bytes]]:
    if not UUID_TEXT.match(report_id):
        return 422, problem(422, "VALIDATION_ERROR", "Entrée invalide", "path.report_id : un UUID est attendu.")
    for index in range(count):
        metadata, content = make_report(index)
        if metadata["report_id"] == report_id.lower():
            return 200, (metadata, content)
    return 404, problem(404, "NOT_FOUND", "Ressource introuvable", "Aucun rapport avec cet identifiant.")


def make_handler(upstream: str, count: int):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict):
            content_type = "application/json" if status < 400 else "application/problem+json"
            self._send(status, json.dumps(payload).encode(), content_type, {"X-Novaria-Maquette": "reports"})

        def _call_upstream(self, path: str, body: bytes | None = None) -> tuple[int, bytes, str]:
            headers = {name: self.headers[name] for name in FORWARDED_HEADERS if self.headers.get(name)}
            request = urllib.request.Request(upstream + path, data=body, headers=headers, method=self.command)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 : adresse http(s) vérifiée au démarrage
                    return response.status, response.read(), response.headers.get("Content-Type", "application/json")
            except urllib.error.HTTPError as error:
                return error.code, error.read(), error.headers.get("Content-Type", "application/json")

        def _caller_is_refused(self) -> tuple[int, bytes, str] | None:
            """Présente le jeton de l'appelant à l'API : sa réponse d'échec (401, 502…) est transmise telle quelle."""
            try:
                status, payload, content_type = self._call_upstream(CURRENT_USER_PATH)
            except urllib.error.URLError:
                return 502, json.dumps(problem(502, "UPSTREAM_UNAVAILABLE", "API injoignable")).encode(), "application/problem+json"
            return None if status == 200 else (status, payload, content_type)

        def _handle(self):
            parsed = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            content = CONTENT_PATH.match(parsed.path)
            if self.command == "GET" and (parsed.path == REPORTS_PATH or content):
                refused = self._caller_is_refused()
                if refused:
                    return self._send(*refused)
                if content is None:
                    return self._send_json(*list_reports(count, urllib.parse.parse_qs(parsed.query)))
                status, found = find_report(count, content.group(1))
                if status != 200:
                    return self._send_json(status, found)  # type: ignore[arg-type]
                metadata, pdf = found  # type: ignore[misc]
                return self._send(200, pdf, "application/pdf", {
                    "Content-Disposition": f'attachment; filename="{metadata["file_name"]}"',
                    "X-Novaria-Maquette": "reports",
                })
            try:
                status, payload, content_type = self._call_upstream(self.path, body)
            except urllib.error.URLError:
                return self._send(502, json.dumps(problem(502, "UPSTREAM_UNAVAILABLE", "API injoignable")).encode(), "application/problem+json")
            self._send(status, payload, content_type)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

        def log_message(self, format, *args):  # noqa: A002 : signature imposée ; ni en-têtes ni jetons dans les journaux
            sys.stderr.write(f"maquette {self.command} {urllib.parse.urlsplit(self.path).path} -> {args[1] if len(args) > 1 else ''}\n")

    return Handler


def make_server(upstream: str, port: int, count: int = DEFAULT_COUNT, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    if not upstream.startswith(("http://", "https://")):
        raise ValueError("L'adresse de l'API doit commencer par http:// ou https://")
    if not 0 <= count <= 100_000:
        raise ValueError("Le nombre de rapports doit être compris entre 0 et 100 000")
    return ThreadingHTTPServer((host, port), make_handler(upstream.rstrip("/"), count))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream", default="http://127.0.0.1:8000", help="API de traitement")
    parser.add_argument("--port", type=int, default=8002, help="port d'écoute (127.0.0.1)")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="nombre de rapports fictifs (0 : liste vide)")
    options = parser.parse_args(argv)
    try:
        server = make_server(options.upstream, options.port, options.count)
    except (ValueError, OSError) as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        return 1
    print(f"MAQUETTE de /api/v1/reports : http://127.0.0.1:{options.port}  (API : {options.upstream} ; {options.count} rapports fictifs ; Ctrl+C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
