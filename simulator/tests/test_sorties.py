"""Destinations, débit réglable et ligne de commande."""

import contextlib
import hashlib
import io
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile

from helpers import START, config, digest, lines, play

from novaria_sim.anomalies import parse_spec
from novaria_sim.cli import main, parse_rate
from novaria_sim.pacing import Pacer
from novaria_sim.run import Run
from novaria_sim.runner import execute
from novaria_sim.sinks import CollecteSink, RunDirectory


class FauxServeur:
    """Une collecte de bouchon : 202 ACCEPTED / DUPLICATE (même id), 422 si le comptage est négatif."""

    def __init__(self):
        self.ids = set()
        self.requests = 0
        self.clients = set()
        faux = self

        class Gestionnaire(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            wbufsize = 65536  # en-têtes et corps dans un seul envoi (sinon Nagle + ACK retardé : 40 ms par réponse)

            def do_POST(self):  # noqa: N802
                faux.requests += 1
                faux.clients.add(self.client_address[1])
                corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path != "/api/v1/measurements":
                    return self.repondre(404, {"detail": "introuvable"})
                if corps["data"]["vehicle_count"] < 0:
                    return self.repondre(422, {"code": "VALIDATION_ERROR"})
                statut = "DUPLICATE" if corps["id"] in faux.ids else "ACCEPTED"
                faux.ids.add(corps["id"])
                self.repondre(202, {"event_id": corps["id"], "status": statut})

            def repondre(self, code, corps):
                octets = json.dumps(corps).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(octets)))
                self.end_headers()
                self.wfile.write(octets)

            def log_message(self, *args):
                pass

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"
        self.fil = threading.Thread(target=self.serveur.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)

    def __enter__(self):
        self.fil.start()
        return self

    def __exit__(self, *args):
        self.serveur.shutdown()
        self.serveur.server_close()


class Horloge:
    def __init__(self):
        self.now = 0.0
        self.pauses = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.pauses.append(seconds)
        self.now += seconds


class DebitReglable(unittest.TestCase):
    def test_n_messages_a_r_par_seconde_prennent_n_moins_un_sur_r_secondes(self):
        horloge = Horloge()
        pacer = Pacer(50.0, horloge.clock, horloge.sleep)
        for _ in range(101):
            pacer.wait()
        self.assertAlmostEqual(horloge.now, 100 / 50.0)  # le premier part tout de suite

    def test_sans_debit_aucune_attente(self):
        horloge = Horloge()
        for rate in (None, 0, 0.0):
            pacer = Pacer(rate, horloge.clock, horloge.sleep)
            for _ in range(1000):
                pacer.wait()
        self.assertEqual(horloge.pauses, [])

    def test_un_retard_de_la_machine_n_est_pas_rattrape_par_une_rafale_infinie(self):
        horloge = Horloge()
        pacer = Pacer(10.0, horloge.clock, horloge.sleep)
        pacer.wait()
        horloge.now += 5.0  # la machine a pris du retard
        for _ in range(3):
            pacer.wait()
        self.assertEqual(horloge.pauses, [])  # en retard : plus d'attente, mais jamais de pause négative

    def test_debit_negatif_refuse(self):
        with self.assertRaises(ValueError):
            Pacer(-1.0)

    def test_le_debit_est_tenu_pour_de_vrai(self):
        # Borne basse seulement (un test de durée maximale serait fragile) : 120 messages à 400 par seconde, au moins 0,29 s.
        run = Run(config(minutes=1))
        envoyes = []

        class Compteur:
            def send(self, delivery):
                envoyes.append(delivery)

            def close(self):
                pass

        debut = time.monotonic()
        stats = execute(run, [Compteur()], None, Pacer(400.0), None, None)
        # 1 minute = 6 intervalles de 24 messages = 144 ; le dernier part à 143 / 400 s
        self.assertEqual(stats.delivered, 144)
        self.assertGreaterEqual(time.monotonic() - debut, 143 / 400 - 0.02)

    def test_realtime_vaut_vingt_quatre_capteurs_toutes_les_dix_secondes(self):
        self.assertAlmostEqual(parse_rate("realtime"), 2.4)
        self.assertEqual(parse_rate("1500"), 1500.0)
        for mauvais in ("vite", "-3"):
            with self.assertRaises(ValueError):
                parse_rate(mauvais)

    def test_l_arret_est_pris_en_compte_au_milieu_d_un_intervalle(self):
        # À 1 message par seconde, un intervalle (24 messages) dure 24 s : attendre sa fin rendrait l'arrêt inutilisable.
        arret = threading.Event()

        class ArretApresCinq:
            def __init__(self):
                self.recus = 0

            def send(self, delivery):
                self.recus += 1
                if self.recus == 5:
                    arret.set()

            def close(self):
                pass

        sink = ArretApresCinq()
        stats = execute(Run(config()), [sink], None, None, arret)
        self.assertTrue(stats.stopped)
        self.assertEqual((sink.recus, stats.delivered), (5, 5))  # le cinquième message est le dernier

    def test_l_arret_demande_interrompt_le_run(self):
        run = Run(config())
        arret = threading.Event()
        arret.set()
        stats = execute(run, [], None, None, arret)
        self.assertTrue(stats.stopped)
        self.assertEqual(stats.delivered, 0)


class DossierDeRun(unittest.TestCase):
    def ecrire(self, racine, **kwargs):
        dossier = Path(racine) / "run"
        repertoire = RunDirectory(dossier)
        run = Run(config(**kwargs))
        execute(run, [repertoire.messages], repertoire.truth)
        return dossier, repertoire.close(run)

    def test_trois_fichiers_dont_la_verite_terrain_a_part(self):
        with tempfile.TemporaryDirectory() as racine:
            dossier, manifeste = self.ecrire(racine, minutes=2)
            self.assertEqual(sorted(p.name for p in dossier.iterdir()), ["manifest.json", "mesures.jsonl", "verite-terrain.jsonl"])
            messages = (dossier / "mesures.jsonl").read_text(encoding="utf-8")
            verite = (dossier / "verite-terrain.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("label_state", messages)
        self.assertIn("label_state", verite)
        self.assertEqual(len(messages.splitlines()), 24 * 12)
        self.assertEqual(len(verite.splitlines()), 24 * 12)
        self.assertEqual(manifeste["files"]["mesures.jsonl"]["lines"], 24 * 12)

    def test_le_manifeste_donne_l_empreinte_exacte_de_chaque_fichier(self):
        with tempfile.TemporaryDirectory() as racine:
            dossier, manifeste = self.ecrire(racine)
            for nom, info in manifeste["files"].items():
                with self.subTest(fichier=nom):
                    self.assertEqual(hashlib.sha256((dossier / nom).read_bytes()).hexdigest(), info["sha256"])
            relu = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(relu, manifeste)

    def test_le_manifeste_decrit_le_run_sans_horloge(self):
        with tempfile.TemporaryDirectory() as racine:
            _, manifeste = self.ecrire(racine, anomalies=[parse_spec("muet:sensor=SENSOR_007,at=+60,duration=40s", START)])
        self.assertEqual(manifeste["run_id"], "run-test")
        self.assertEqual(manifeste["provenance"], {"source_type": "SIMULATED", "scenario_id": "heure-de-pointe", "seed": 42})
        self.assertEqual((manifeste["interval_s"], manifeste["sensors"], manifeste["intervals"]), (10, 24, 60))
        self.assertEqual(manifeste["anomalies"], [{"intervals": 4, "kind": "muet", "sensor_id": "SENSOR_007", "start": "2026-10-20T07:31:00Z"}])
        self.assertEqual({"start", "end"}, {k for k in manifeste if k in ("start", "end")})
        self.assertFalse([k for k in manifeste if "generated" in k or "date" in k or "time" in k])

    def test_fichiers_en_utf8_avec_fins_de_ligne_lf(self):
        with tempfile.TemporaryDirectory() as racine:
            dossier, _ = self.ecrire(racine, minutes=1)
            for fichier in dossier.iterdir():
                with self.subTest(fichier=fichier.name):
                    octets = fichier.read_bytes()
                    octets.decode("utf-8")
                    self.assertNotIn(b"\r", octets)
                    self.assertTrue(octets.endswith(b"\n"))

    def test_le_dossier_se_relit_comme_un_run_rejoue(self):
        with tempfile.TemporaryDirectory() as racine:
            dossier, _ = self.ecrire(racine)
            ecrit = (dossier / "mesures.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(ecrit, lines(play(config())[0]))
        self.assertEqual(digest(ecrit), digest(lines(play(config())[0])))


class VersLaCollecte(unittest.TestCase):
    def envoyer(self, url, **kwargs):
        sink = CollecteSink(url)
        execute(Run(config(**kwargs)), [sink])
        sink.close()
        return sink.receipts

    def test_chaque_message_est_accepte(self):
        with FauxServeur() as faux:
            recus = self.envoyer(faux.url, minutes=1)
        self.assertEqual((recus.accepted, recus.duplicates, recus.rejected, recus.errors), (144, 0, 0, 0))

    def test_un_doublon_est_recu_comme_doublon(self):
        with FauxServeur() as faux:
            recus = self.envoyer(faux.url, anomalies=[parse_spec("doublon:sensor=SENSOR_001,at=+20,copies=3", START)])
        self.assertEqual((recus.accepted, recus.duplicates), (24 * 60, 3))

    def test_la_connexion_est_reutilisee(self):
        with FauxServeur() as faux:
            self.envoyer(faux.url, minutes=1)
        self.assertEqual(len(faux.clients), 1)
        self.assertEqual(faux.requests, 144)

    def test_une_collecte_injoignable_est_comptee_pas_cachee(self):
        recus = self.envoyer("http://127.0.0.1:9", minutes=1)
        self.assertEqual((recus.accepted, recus.errors), (0, 144))
        self.assertIsNotNone(recus.last_error)

    def test_une_adresse_qui_n_est_pas_http_est_refusee(self):
        for adresse in ("file:///etc/passwd", "collecte:8000", "ftp://x"):
            with self.subTest(adresse=adresse), self.assertRaises(ValueError):
                CollecteSink(adresse)


class LigneDeCommande(unittest.TestCase):
    def lancer(self, *argv):
        sortie, erreur = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            code = main(list(argv))
        return code, sortie.getvalue(), erreur.getvalue()

    BASE = ("run", "--scenario", "heure-de-pointe", "--seed", "42", "--run-id", "run-test", "--start", "2026-10-20T07:30:00Z", "--duration", "1m")

    def test_les_scenarios_se_listent(self):
        code, sortie, _ = self.lancer("scenarios")
        self.assertEqual(code, 0)
        self.assertEqual([ligne.split()[0] for ligne in sortie.splitlines()], ["journee-calme", "heure-de-pointe", "incident-ponctuel"])

    def test_stdout_ne_contient_que_des_messages_json_un_par_ligne(self):
        code, sortie, erreur = self.lancer(*self.BASE, "--stdout")
        self.assertEqual(code, 0)
        documents = [json.loads(ligne) for ligne in sortie.splitlines()]
        self.assertEqual(len(documents), 144)
        self.assertTrue(all(d["type"] == "novaria.iot.measurement.v1" for d in documents))
        self.assertEqual(json.loads(erreur)["messages"], 144)  # le résumé va ailleurs

    def test_la_sortie_standard_est_celle_du_fichier(self):
        _, sortie, _ = self.lancer(*self.BASE, "--stdout")
        self.assertEqual(sortie.splitlines(), lines(play(config(minutes=1))[0]))

    def test_il_faut_une_destination(self):
        code, _, erreur = self.lancer(*self.BASE)
        self.assertEqual(code, 2)
        self.assertIn("--out", erreur)

    def test_les_erreurs_de_saisie_sortent_en_code_2_avec_un_message(self):
        for argv, fragment in (
            ((*self.BASE, "--stdout", "--anomaly", "muet:sensor=SENSOR_999"), "capteur inconnu"),
            ((*self.BASE, "--stdout", "--end", "2026-10-20T08:00:00Z"), "s'excluent"),
            ((*self.BASE, "--stdout", "--rate", "vite"), "débit illisible"),
            (("run", "--scenario", "heure-de-pointe", "--stdout", "--seed", "-1", "--duration", "1m"), "graine"),
            (("run", "--scenario", "heure-de-pointe", "--stdout", "--run-id", "a:b", "--duration", "1m"), "run_id"),
        ):
            with self.subTest(argv=argv[-2:]):
                code, sortie, erreur = self.lancer(*argv)
                self.assertEqual(code, 2)
                self.assertEqual(sortie, "")
                self.assertIn(fragment, erreur)

    def test_un_run_avec_anomalies_se_rejoue_depuis_son_manifeste(self):
        with tempfile.TemporaryDirectory() as racine:
            premier, second = Path(racine) / "premier", Path(racine) / "second"
            self.lancer(*self.BASE, "--out", str(premier), "--anomaly", "doublon:sensor=SENSOR_001,at=+20,copies=2",
                        "--anomaly", "retard:sensor=SENSOR_010,at=+30,delay=25")
            manifeste = json.loads((premier / "manifest.json").read_text(encoding="utf-8"))
            fichier = Path(racine) / "anomalies.json"
            fichier.write_text(json.dumps(manifeste["anomalies"]), encoding="utf-8")
            self.lancer(*self.BASE, "--out", str(second), "--anomalies-file", str(fichier))
            self.assertEqual((premier / "mesures.jsonl").read_bytes(), (second / "mesures.jsonl").read_bytes())
            self.assertEqual((premier / "manifest.json").read_bytes(), (second / "manifest.json").read_bytes())

    def test_la_verite_terrain_s_ecrit_a_part_avec_stdout(self):
        with tempfile.TemporaryDirectory() as racine:
            fichier = Path(racine) / "verite.jsonl"
            code, sortie, _ = self.lancer(*self.BASE, "--stdout", "--truth", str(fichier))
            verite = fichier.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertNotIn("label_state", sortie)
        self.assertEqual(len(verite.splitlines()), 144)

    def test_envoi_a_la_collecte_et_resume(self):
        with FauxServeur() as faux:
            code, _, erreur = self.lancer(*self.BASE, "--collecte-url", faux.url, "--anomaly", "doublon:sensor=SENSOR_001,at=+20,copies=2")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(erreur)["collecte"], {"accepted": 144, "duplicates": 2, "rejected": 0, "errors": 0, "last_error": None})

    def test_collecte_injoignable_code_de_sortie_1(self):
        code, _, erreur = self.lancer(*self.BASE, "--collecte-url", "http://127.0.0.1:9")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(erreur)["collecte"]["errors"], 144)

    def test_le_nombre_de_messages_suit_la_duree(self):
        for duree, attendu in (("30s", 72), ("1m", 144), ("5m", 720)):
            with self.subTest(duree=duree):
                _, sortie, _ = self.lancer(*self.BASE[:-1], duree, "--stdout")
                self.assertEqual(len(sortie.splitlines()), attendu)


if __name__ == "__main__":
    unittest.main()
