"""Tests de scripts/dev/forecast_stub.py : la maquette de /api/v1/forecasts, devant une fausse API (ports locaux libres).

Lancer :  python3 -m unittest discover -s scripts/dev -p "test_forecast_stub.py" -v
"""
import contextlib
import io
import json
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forecast_stub as stub  # noqa: E402

PROVENANCE = {"source_type": "SIMULATED", "run_id": "run-demo", "scenario_id": "demo", "seed": 0}
START = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


def indicator(segment: str, minutes: int, ratio: float | None, size: int = 300) -> dict:
    start = START + timedelta(minutes=minutes)
    return {
        "indicator_id": f"run-demo:{segment}:{size}:{int(start.timestamp() * 1000)}", "road_segment_id": segment,
        "intersection_id": "INT_01", "window_start": stub.iso(start), "window_size_s": size, "vehicle_count": 5,
        "flow_veh_per_min": 1.0, "average_speed_kmh": None if ratio is None else ratio * 50, "speed_ratio": ratio,
        "sample_count": 6, "expected_sample_count": 6, "congestion_state": "FREE_FLOW", "classifier_version": "x",
        "provenance": PROVENANCE,
    }


# Deux tronçons, douze fenêtres de 5 minutes de 08:00 à 08:55 (fin des données : 09:00) ; le ratio monte de 0,010 par fenêtre.
DATA = [indicator(segment, 5 * n, round(0.4 + 0.01 * n + offset, 3))
        for n in range(12) for segment, offset in (("ROAD_001", 0.0), ("ROAD_002", 0.1))]


class FakeApi(BaseHTTPRequestHandler):
    seen: list[tuple[str, str, dict[str, str], bytes]] = []
    data: list[dict] = DATA

    def _handle(self):
        parsed = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        type(self).seen.append((self.command, self.path, {k: v for k, v in self.headers.items()}, body))

        def reply(status, payload, content_type="application/json"):
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        if parsed.path == "/api/v1/auth/login":
            return reply(200, {"access_token": "jeton-de-test", "token_type": "bearer", "expires_in": 1800})
        if not self.headers.get("Authorization"):
            return reply(401, {"type": "about:blank", "title": "Non authentifié", "status": 401, "code": "UNAUTHENTICATED"},
                         "application/problem+json")
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        rows = [r for r in type(self).data if r["window_size_s"] == int(query.get("window_size_s", 60))]
        if "run_id" in query:
            rows = [r for r in rows if r["provenance"]["run_id"] == query["run_id"]]
        if "from" in query:
            rows = [r for r in rows if r["window_start"] >= query["from"]]
        if "to" in query:
            rows = [r for r in rows if r["window_start"] < query["to"]]
        rows.sort(key=lambda r: (r["window_start"], r["road_segment_id"]), reverse=True)
        reply(200, {"items": rows[: int(query.get("limit", 100))], "next_cursor": None})

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


def get(base: str, path: str, token: str | None = "jeton-de-test"):
    request = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read()), dict(response.headers)
    except urllib.error.HTTPError as error:
        with error:  # referme la réponse d'erreur
            return error.code, json.loads(error.read()), dict(error.headers)


class StubTests(unittest.TestCase):
    def setUp(self):
        FakeApi.seen = []
        FakeApi.data = DATA

    @contextlib.contextmanager
    def stack(self, back_minutes=60, data=None):
        if data is not None:
            FakeApi.data = data
        with contextlib.redirect_stderr(io.StringIO()):  # les lignes de journal de la maquette n'encombrent pas les tests
            with serving(ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)) as upstream:
                with serving(stub.make_server(upstream, 0, back_minutes)) as base:
                    yield base

    def test_n_invente_rien_quand_aucune_fenetre_n_est_terminee_a_l_emission(self):
        # Fin des données 09:00, émission 60 min avant = 08:00 : la première fenêtre (08:00) finit à 08:05, donc rien n'est connu.
        with self.stack(back_minutes=60) as base:
            status, body, headers = get(base, "/api/v1/forecasts?horizon_min=30")
        self.assertEqual((status, body), (200, {"items": []}))
        self.assertEqual(headers["X-Novaria-Maquette"], "forecasts")

    def test_emission_dans_les_donnees(self):
        with self.stack(back_minutes=30) as base:
            status, body, _ = get(base, "/api/v1/forecasts?horizon_min=30")
        self.assertEqual(status, 200)
        # Émission 08:30 ; dernière fenêtre terminée avant : celle de 08:25 (fin 08:30), 6e fenêtre (n = 5) : 0,45 / 0,55.
        by_segment = {item["road_segment_id"]: item for item in body["items"]}
        self.assertEqual(sorted(by_segment), ["ROAD_001", "ROAD_002"])
        first = by_segment["ROAD_001"]
        self.assertEqual(first["issued_at"], "2026-10-30T08:30:00Z")
        self.assertEqual(first["target_time"], "2026-10-30T09:00:00Z")
        self.assertEqual(first["horizon_min"], 30)
        self.assertEqual(first["predicted_speed_ratio"], 0.45)
        self.assertEqual(by_segment["ROAD_002"]["predicted_speed_ratio"], 0.55)

    def test_la_reponse_porte_les_champs_du_contrat_et_se_dit_maquette(self):
        with self.stack(back_minutes=30) as base:
            _, body, _ = get(base, "/api/v1/forecasts")
        item = body["items"][0]
        for champ in ("road_segment_id", "issued_at", "horizon_min", "target_time", "predicted_speed_ratio", "model", "provenance"):
            self.assertIn(champ, item)
        self.assertEqual(item["horizon_min"], 15)  # défaut du contrat
        self.assertEqual(item["model"]["kind"], "REFERENCE")
        self.assertIn("maquette", item["model"]["name"])
        self.assertIsNone(item["model"]["run_id"])
        self.assertEqual(item["provenance"], PROVENANCE)
        self.assertEqual(item["predicted_state"], "FREE_FLOW")

    def test_filtre_par_troncon(self):
        with self.stack(back_minutes=30) as base:
            _, body, _ = get(base, "/api/v1/forecasts?road_segment_id=ROAD_002&horizon_min=5")
        self.assertEqual([i["road_segment_id"] for i in body["items"]], ["ROAD_002"])

    def test_sans_retard_l_emission_est_la_fin_des_donnees(self):
        with self.stack(back_minutes=0) as base:
            _, body, _ = get(base, "/api/v1/forecasts")
        self.assertEqual(body["items"][0]["issued_at"], "2026-10-30T09:00:00Z")
        self.assertEqual(body["items"][0]["predicted_speed_ratio"], 0.51)  # dernière fenêtre, n = 11

    def test_passe_aux_fenetres_de_5_minutes_quand_celles_d_une_minute_sont_vides(self):
        with self.stack(back_minutes=0) as base:
            get(base, "/api/v1/forecasts")
        tailles = [urllib.parse.parse_qs(urllib.parse.urlsplit(path).query).get("window_size_s") for _, path, _, _ in FakeApi.seen]
        self.assertEqual(tailles[0], ["60"])
        self.assertIn(["300"], tailles)

    def test_ignore_un_troncon_sans_ratio(self):
        data = [indicator("ROAD_001", 0, None), indicator("ROAD_002", 0, 0.5)]
        with self.stack(back_minutes=0, data=data) as base:
            _, body, _ = get(base, "/api/v1/forecasts")
        self.assertEqual([i["road_segment_id"] for i in body["items"]], ["ROAD_002"])

    def test_sans_donnee_aucune_prevision(self):
        with self.stack(data=[]) as base:
            status, body, _ = get(base, "/api/v1/forecasts")
        self.assertEqual((status, body), (200, {"items": []}))

    def test_transmet_le_refus_de_l_api_sans_jeton(self):
        with self.stack() as base:
            status, body, _ = get(base, "/api/v1/forecasts", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "UNAUTHENTICATED")

    def test_transmet_le_jeton_de_l_appelant_a_l_api(self):
        with self.stack(back_minutes=30) as base:
            get(base, "/api/v1/forecasts", token="mon-jeton")
        envoyes = {headers.get("Authorization") for _, _, headers, _ in FakeApi.seen}
        self.assertEqual(envoyes, {"Bearer mon-jeton"})

    def test_transmet_les_autres_routes_telles_quelles(self):
        with self.stack() as base:
            request = urllib.request.Request(
                base + "/api/v1/auth/login", data=b'{"username":"a","password":"b"}', method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                corps = json.loads(response.read())
        self.assertEqual(corps["access_token"], "jeton-de-test")
        methode, chemin, headers, envoye = FakeApi.seen[0]
        self.assertEqual((methode, chemin, envoye), ("POST", "/api/v1/auth/login", b'{"username":"a","password":"b"}'))
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_dit_502_quand_l_api_est_injoignable(self):
        with contextlib.redirect_stderr(io.StringIO()), serving(stub.make_server("http://127.0.0.1:9", 0, 60)) as base:  # port 9 : rien n'écoute
            status, body, _ = get(base, "/api/v1/indicators")
        self.assertEqual(status, 502)
        self.assertEqual(body["code"], "UPSTREAM_UNAVAILABLE")

    def test_refuse_une_adresse_qui_n_est_pas_http(self):
        with self.assertRaises(ValueError):
            stub.make_server("file:///etc/passwd", 0, 60)
        with contextlib.redirect_stderr(io.StringIO()) as erreur:
            self.assertEqual(stub.main(["--upstream", "ftp://x", "--port", "0"]), 1)
        self.assertIn("http", erreur.getvalue())

    def test_les_journaux_n_ecrivent_ni_jeton_ni_requete_complete(self):
        with self.stack(back_minutes=30) as base, contextlib.redirect_stderr(io.StringIO()) as journal:
            get(base, "/api/v1/forecasts?road_segment_id=ROAD_001", token="secret-a-ne-pas-ecrire")
        texte = journal.getvalue()
        self.assertNotIn("secret-a-ne-pas-ecrire", texte)
        self.assertNotIn("road_segment_id", texte)


if __name__ == "__main__":
    unittest.main()
