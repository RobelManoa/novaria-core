"""Banc de débit de la collecte (MS-08) : l'outil de mesure est lui-même vérifié, avec un faux serveur local.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_bench_collecte.py"   (Windows : py -3 ...)
"""
import contextlib
import io
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RACINE / "contracts"))
import bench_collecte as banc  # noqa: E402

try:
    from validate_events import validate_event
except ImportError:  # jsonschema absent : les contrôles de conformité sont ignorés
    validate_event = None


class FauxServeur:
    """Une collecte factice : 202 ACCEPTED la première fois qu'un identifiant arrive, 202 DUPLICATE ensuite, 422 si invalide."""

    def __init__(self, panne_apres: int | None = None):
        self.vus: set[str] = set()
        self.recus = 0
        self.panne_apres = panne_apres
        outer = self

        class Gestionnaire(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                self.repondre(200, {"status": "ok"})

            def do_POST(self):
                corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.recus += 1
                if outer.panne_apres is not None and outer.recus > outer.panne_apres:
                    self.repondre(503, {"status": 503, "code": "UPSTREAM_UNAVAILABLE"})
                elif corps["data"]["occupancy_rate"] > 1:
                    self.repondre(422, {"status": 422, "code": "VALIDATION_ERROR"})
                else:
                    statut = "DUPLICATE" if corps["id"] in outer.vus else "ACCEPTED"
                    outer.vus.add(corps["id"])
                    self.repondre(202, {"event_id": corps["id"], "status": statut})

            def repondre(self, code, corps):
                donnees = json.dumps(corps).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.serveur.shutdown()
        self.serveur.server_close()


def lancer(*args: str):
    sortie, erreur = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
        code = banc.main(list(args))
    return code, sortie.getvalue(), erreur.getvalue()


@unittest.skipIf(validate_event is None, "jsonschema et referencing sont nécessaires")
class MessagesDuBanc(unittest.TestCase):
    def test_chaque_mesure_du_banc_respecte_le_contrat(self):
        for index in list(range(0, 60)) + [239, 240, 241, 5000]:
            with self.subTest(index=index):
                self.assertEqual(validate_event(banc.measurement("banc-a1b2c3d4", index)), [])

    def test_les_identifiants_sont_distincts_et_ceux_de_deux_executions_aussi(self):
        premiers = {banc.measurement("banc-a", i)["id"] for i in range(6000)}
        seconds = {banc.measurement("banc-b", i)["id"] for i in range(6000)}
        self.assertEqual(len(premiers), 6000)
        self.assertFalse(premiers & seconds)

    def test_le_message_invalide_viole_le_contrat_et_lui_seul(self):
        defauts = validate_event(banc.invalid("banc-a", 3))
        self.assertEqual(len(defauts), 1)
        self.assertIn("occupancy_rate", defauts[0])

    def test_les_capteurs_et_carrefours_suivent_le_reseau_fixe(self):
        evenements = [banc.measurement("r", i) for i in range(24)]
        self.assertEqual([e["data"]["sensor_id"] for e in evenements], [f"SENSOR_{n:03d}" for n in range(1, 25)])
        self.assertEqual({e["subject"] for e in evenements}, {f"INT_{n:02d}" for n in range(1, 7)})
        self.assertEqual(evenements[0]["subject"], evenements[3]["subject"])
        self.assertNotEqual(evenements[3]["subject"], evenements[4]["subject"])


class Mesure(unittest.TestCase):
    def test_les_percentiles_viennent_des_valeurs_triees(self):
        valeurs = [float(n) for n in range(1, 101)]
        self.assertEqual(banc.percentile(valeurs, 0.5), 51.0)
        self.assertEqual(banc.percentile(valeurs, 0.99), 100.0)
        self.assertEqual(banc.percentile([7.0], 0.95), 7.0)

    def test_un_palier_compte_chaque_reponse_et_calcule_un_debit(self):
        with FauxServeur() as faux:
            bodies = banc.encode([banc.measurement("banc-t", i) for i in range(60)])
            ligne = banc.run_level(faux.url, bodies, 4, None)
        self.assertEqual(ligne["answers"], {"202 ACCEPTED": 60})
        self.assertEqual(ligne["transport_errors"], 0)
        self.assertGreater(ligne["per_second"], 0)
        self.assertLessEqual(ligne["p50_ms"], ligne["p95_ms"])
        self.assertLessEqual(ligne["p95_ms"], ligne["p99_ms"])
        self.assertLessEqual(ligne["p99_ms"], ligne["max_ms"])
        self.assertIsNone(ligne["cpu_max_percent"])

    def test_les_messages_sont_repartis_entre_les_connexions_sans_perte_ni_doublon(self):
        with FauxServeur() as faux:
            ligne = banc.run_level(faux.url, banc.encode([banc.measurement("banc-t", i) for i in range(101)]), 7, None)
            self.assertEqual(len(faux.vus), 101)
        self.assertEqual(sum(ligne["answers"].values()), 101)

    def test_un_serveur_qui_tombe_est_compte_en_erreurs_pas_en_succes(self):
        with FauxServeur(panne_apres=10) as faux:
            ligne = banc.run_level(faux.url, banc.encode([banc.measurement("banc-t", i) for i in range(30)]), 1, None)
        self.assertEqual(ligne["answers"], {"202 ACCEPTED": 10, "503 UPSTREAM_UNAVAILABLE": 20})

    def test_l_echantillonnage_du_processeur_lit_docker_stats(self):
        sortie = mock.Mock(stdout="37.5%\n")
        with FauxServeur() as faux, mock.patch("subprocess.run", return_value=sortie) as docker:
            ligne = banc.run_level(
                faux.url, banc.encode([banc.measurement("banc-t", i) for i in range(400)]), 1, "collecte-1", sample_every=0.01
            )
        self.assertEqual(docker.call_args.args[0][:3], ["docker", "stats", "--no-stream"])
        self.assertEqual(ligne["cpu_max_percent"], 37.5)

    def test_une_sortie_illisible_de_docker_stats_est_ignoree(self):
        sortie = mock.Mock(stdout="--\n")
        with FauxServeur() as faux, mock.patch("subprocess.run", return_value=sortie):
            ligne = banc.run_level(
                faux.url, banc.encode([banc.measurement("banc-t", i) for i in range(400)]), 1, "collecte-1", sample_every=0.01
            )
        self.assertIsNone(ligne["cpu_max_percent"])


class LigneDeCommande(unittest.TestCase):
    def test_contre_un_serveur_correct_le_banc_reussit_et_donne_le_debit_maximal(self):
        with FauxServeur() as faux:
            code, sortie, _ = lancer("--url", faux.url, "--messages", "40", "--levels", "1,4")
        self.assertEqual(code, 0)
        self.assertIn("Débit maximal mesuré", sortie)
        self.assertIn("mêmes messages (doublons)", sortie)
        self.assertIn("{'202 DUPLICATE': 40}", sortie)
        self.assertIn("{'422 VALIDATION_ERROR': 40}", sortie)
        self.assertIn("Réponses inattendues ou erreurs de transport : 0", sortie)

    def test_une_reponse_inattendue_fait_echouer_le_banc(self):
        with FauxServeur(panne_apres=50) as faux:
            code, sortie, _ = lancer("--url", faux.url, "--messages", "40", "--levels", "1")
        self.assertEqual(code, 1)
        self.assertNotIn("inattendues ou erreurs de transport : 0", sortie)

    def test_sans_collecte_le_message_dit_quoi_faire_et_le_code_est_2(self):
        code, _, erreur = lancer("--url", "http://127.0.0.1:9", "--messages", "10", "--levels", "1")
        self.assertEqual(code, 2)
        self.assertIn("dev.py up", erreur)

    def test_des_paliers_incoherents_sont_refuses(self):
        for args in (("--levels", "0"), ("--levels", "a,b"), ("--levels", "50", "--messages", "10")):
            with self.subTest(args=args):
                code, _, erreur = lancer("--url", "http://127.0.0.1:9", *args)
                self.assertEqual(code, 2)
                self.assertIn("--levels", erreur)

    def test_l_option_json_ajoute_le_tableau_des_resultats(self):
        with FauxServeur() as faux:
            code, sortie, _ = lancer("--url", faux.url, "--messages", "20", "--levels", "2", "--json")
        self.assertEqual(code, 0)
        tableau = json.loads(sortie.strip().splitlines()[-1])
        self.assertEqual([ligne["kind"] for ligne in tableau], ["valides", "doublons", "invalides"])


if __name__ == "__main__":
    unittest.main()
