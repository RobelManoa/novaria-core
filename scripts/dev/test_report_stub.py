"""Tests de scripts/dev/report_stub.py : la maquette de /api/v1/reports, devant une fausse API (ports locaux libres).

Lancer :  python3 -m unittest discover -s scripts/dev -p "test_report_stub.py" -v
"""
import contextlib
import hashlib
import io
import json
import re
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import yaml
except ImportError:  # PyYAML est facultatif : le test de concordance avec le contrat est alors ignoré
    yaml = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_stub as stub  # noqa: E402

CONTRAT = Path(__file__).resolve().parents[2] / "contracts" / "openapi" / "traitement.openapi.yaml"
TOKEN = "jeton-de-test"


class FakeApi(BaseHTTPRequestHandler):
    seen: list[tuple[str, str, dict[str, str], bytes]] = []

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        type(self).seen.append((self.command, self.path, {k: v for k, v in self.headers.items()}, body))

        def reply(status, payload):
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json" if status < 400 else "application/problem+json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        if self.path == "/api/v1/auth/login":
            return reply(200, {"access_token": TOKEN, "token_type": "bearer", "expires_in": 1800})
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return reply(401, {"type": "about:blank", "title": "Non authentifié", "status": 401, "code": "UNAUTHENTICATED"})
        reply(200, {"username": "lecteur", "role": "viewer"})

    do_GET = do_POST = _handle

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def serving(server: ThreadingHTTPServer):
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get(base: str, path: str, token: str | None = TOKEN):
    """(statut, corps brut, en-têtes) ; les échecs HTTP sont rendus comme les réussites."""
    request = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(), dict(error.headers)


def get_json(base: str, path: str, token: str | None = TOKEN):
    status, raw, headers = get(base, path, token)
    return status, json.loads(raw), headers


class BuildPdfTests(unittest.TestCase):
    def test_le_pdf_est_bien_forme_et_sa_table_des_references_est_exacte(self):
        pdf = stub.build_pdf(["Ligne (un)", "Ligne \\ deux"])
        self.assertTrue(pdf.startswith(b"%PDF-1.4\n"))
        self.assertTrue(pdf.endswith(b"%%EOF\n"))
        startxref = int(re.search(rb"startxref\n(\d+)\n", pdf).group(1))
        self.assertTrue(pdf[startxref:].startswith(b"xref\n"))
        entries = re.findall(rb"(\d{10}) 00000 n \n", pdf)
        self.assertEqual(len(entries), 5)
        for number, offset in enumerate(entries, start=1):
            self.assertTrue(pdf[int(offset):].startswith(f"{number} 0 obj\n".encode()), number)
        self.assertIn(rb"Ligne \(un\)", pdf)  # parenthèses échappées
        length = int(re.search(rb"/Length (\d+)", pdf).group(1))
        flux = pdf.split(b"stream\n", 1)[1].split(b"\nendstream", 1)[0]
        self.assertEqual(length, len(flux))

    def test_deux_constructions_donnent_les_memes_octets(self):
        self.assertEqual(stub.make_report(2), stub.make_report(2))


class MakeReportTests(unittest.TestCase):
    def test_taille_et_empreinte_sont_celles_des_octets_servis(self):
        metadata, content = stub.make_report(0)
        self.assertEqual(metadata["size_bytes"], len(content))
        self.assertEqual(metadata["sha256"], hashlib.sha256(content).hexdigest())

    def test_le_plus_recent_est_le_jour_de_reference_et_les_suivants_reculent_d_un_jour(self):
        premier, deuxieme = stub.make_report(0)[0], stub.make_report(1)[0]
        self.assertEqual(premier["period_start"], "2026-11-04T00:00:00Z")
        self.assertEqual(premier["period_end"], "2026-11-05T00:00:00Z")
        self.assertEqual(premier["generated_at"], "2026-11-05T00:05:00Z")
        self.assertEqual(deuxieme["period_start"], "2026-11-03T00:00:00Z")
        self.assertNotEqual(premier["report_id"], deuxieme["report_id"])

    def test_la_maquette_se_dit_maquette_dans_le_titre_le_fichier_et_le_contenu(self):
        metadata, content = stub.make_report(0)
        self.assertIn("(maquette)", metadata["title"])
        self.assertIn("maquette", metadata["file_name"])
        self.assertIn(b"MAQUETTE LOCALE", content)


class StubTests(unittest.TestCase):
    def setUp(self):
        FakeApi.seen = []

    @contextlib.contextmanager
    def stack(self, count=3):
        with contextlib.redirect_stderr(io.StringIO()) as journal:  # les lignes de journal n'encombrent pas les tests
            self.journal = journal
            with serving(ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)) as upstream:
                with serving(stub.make_server(upstream, 0, count)) as base:
                    yield base

    def test_la_liste_rend_les_rapports_du_plus_recent_au_plus_ancien(self):
        with self.stack(count=3) as base:
            status, body, headers = get_json(base, "/api/v1/reports")
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Novaria-Maquette"], "reports")
        self.assertIsNone(body["next_cursor"])
        self.assertEqual([i["period_start"][:10] for i in body["items"]], ["2026-11-04", "2026-11-03", "2026-11-02"])
        self.assertEqual([i["generated_at"] for i in body["items"]], sorted((i["generated_at"] for i in body["items"]), reverse=True))

    @unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
    def test_chaque_rapport_porte_exactement_les_champs_du_contrat(self):
        schema = yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))["components"]["schemas"]["Report"]
        with self.stack(count=2) as base:
            _, body, _ = get_json(base, "/api/v1/reports")
        for item in body["items"]:
            self.assertEqual(set(item), set(schema["properties"]))
            self.assertTrue(set(schema["required"]) <= set(item))
            self.assertEqual(item["content_type"], schema["properties"]["content_type"]["enum"][0])
            self.assertRegex(item["sha256"], schema["properties"]["sha256"]["pattern"])
            self.assertGreaterEqual(item["size_bytes"], schema["properties"]["size_bytes"]["minimum"])

    def test_zero_rapport_donne_une_liste_vide(self):
        with self.stack(count=0) as base:
            status, body, _ = get_json(base, "/api/v1/reports")
        self.assertEqual((status, body), (200, {"items": [], "next_cursor": None}))

    def test_pagination_par_curseur_sans_trou_ni_doublon(self):
        with self.stack(count=25) as base:
            pages, cursor = [], None
            while True:
                query = "limit=10" + (f"&cursor={cursor}" if cursor else "")
                status, body, _ = get_json(base, f"/api/v1/reports?{query}")
                self.assertEqual(status, 200)
                pages.append([i["report_id"] for i in body["items"]])
                cursor = body["next_cursor"]
                if cursor is None:
                    break
            _, tout, _ = get_json(base, "/api/v1/reports?limit=500")
        self.assertEqual([len(p) for p in pages], [10, 10, 5])
        self.assertEqual(sum(pages, []), [i["report_id"] for i in tout["items"]])
        self.assertEqual(len(set(sum(pages, []))), 25)

    def test_limite_exactement_egale_au_nombre_de_rapports_n_a_pas_de_page_suivante(self):
        with self.stack(count=10) as base:
            _, body, _ = get_json(base, "/api/v1/reports?limit=10")
        self.assertEqual(len(body["items"]), 10)
        self.assertIsNone(body["next_cursor"])

    def test_refuse_une_limite_ou_un_curseur_invalide(self):
        with self.stack(count=3) as base:
            for query in ("limit=0", "limit=501", "limit=abc", "cursor=n-importe-quoi", "cursor=maquette-99"):
                with self.subTest(query=query):
                    status, body, _ = get_json(base, f"/api/v1/reports?{query}")
                    self.assertEqual((status, body["code"]), (422, "VALIDATION_ERROR"))

    def test_le_telechargement_rend_le_pdf_annonce_par_la_liste(self):
        with self.stack(count=3) as base:
            _, liste, _ = get_json(base, "/api/v1/reports")
            rapport = liste["items"][1]
            status, octets, headers = get(base, f"/api/v1/reports/{rapport['report_id']}/content")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(headers["Content-Disposition"], f'attachment; filename="{rapport["file_name"]}"')
        self.assertEqual(len(octets), rapport["size_bytes"])
        self.assertEqual(hashlib.sha256(octets).hexdigest(), rapport["sha256"])
        self.assertTrue(octets.startswith(b"%PDF-"))

    def test_rapport_inconnu_ou_identifiant_invalide(self):
        with self.stack(count=3) as base:
            inconnu = get_json(base, "/api/v1/reports/00000000-0000-4000-8000-000000000000/content")
            invalide = get_json(base, "/api/v1/reports/pas-un-uuid/content")
        self.assertEqual((inconnu[0], inconnu[1]["code"]), (404, "NOT_FOUND"))
        self.assertEqual((invalide[0], invalide[1]["code"]), (422, "VALIDATION_ERROR"))
        self.assertEqual(inconnu[2]["Content-Type"], "application/problem+json")

    def test_un_rapport_hors_du_nombre_demande_n_existe_pas(self):
        autre = stub.make_report(5)[0]["report_id"]
        with self.stack(count=3) as base:
            status, _, _ = get_json(base, f"/api/v1/reports/{autre}/content")
        self.assertEqual(status, 404)

    def test_sans_jeton_valide_la_refus_de_l_api_est_transmis(self):
        with self.stack() as base:
            liste = get_json(base, "/api/v1/reports", token=None)
            contenu = get_json(base, f"/api/v1/reports/{stub.make_report(0)[0]['report_id']}/content", token="faux")
        for status, body, _ in (liste, contenu):
            self.assertEqual((status, body["code"]), (401, "UNAUTHENTICATED"))

    def test_presente_le_jeton_de_l_appelant_a_l_api_et_n_en_garde_aucun(self):
        with self.stack() as base:
            get(base, "/api/v1/reports")
        self.assertEqual([(m, p) for m, p, _, _ in FakeApi.seen], [("GET", "/api/v1/auth/me")])
        self.assertEqual(FakeApi.seen[0][2]["Authorization"], f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, self.journal.getvalue())
        self.assertIn("maquette GET /api/v1/reports", self.journal.getvalue())

    def test_transmet_les_autres_routes_telles_quelles(self):
        with self.stack() as base:
            request = urllib.request.Request(
                base + "/api/v1/auth/login", data=b'{"username":"a","password":"b"}', method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                corps = json.loads(response.read())
        self.assertEqual(corps["access_token"], TOKEN)
        methode, chemin, _, envoye = FakeApi.seen[0]
        self.assertEqual((methode, chemin, envoye), ("POST", "/api/v1/auth/login", b'{"username":"a","password":"b"}'))

    def test_api_injoignable_donne_un_502_au_format_probleme(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with serving(stub.make_server("http://127.0.0.1:9", 0, 3)) as base:
                liste = get_json(base, "/api/v1/reports")
                autre = get_json(base, "/api/v1/indicators")
        for status, body, _ in (liste, autre):
            self.assertEqual((status, body["code"]), (502, "UPSTREAM_UNAVAILABLE"))


class MakeServerTests(unittest.TestCase):
    def test_refuse_une_adresse_d_api_sans_schema(self):
        with self.assertRaises(ValueError):
            stub.make_server("127.0.0.1:8000", 0)

    def test_refuse_un_nombre_de_rapports_hors_bornes(self):
        for count in (-1, 100_001):
            with self.subTest(count=count), self.assertRaises(ValueError):
                stub.make_server("http://127.0.0.1:8000", 0, count)

    def test_main_signale_une_erreur_de_demarrage(self):
        with contextlib.redirect_stderr(io.StringIO()) as erreur:
            code = stub.main(["--upstream", "pas-une-adresse"])
        self.assertEqual(code, 1)
        self.assertIn("ERREUR", erreur.getvalue())


if __name__ == "__main__":
    unittest.main()
