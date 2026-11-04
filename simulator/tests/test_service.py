"""Service HTTP du conteneur : sonde inchangée, lancement d'un run, anomalies à la demande."""

import contextlib
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

from helpers import SIMULATOR  # noqa: F401  (met le simulateur dans sys.path)

from novaria_sim.service import Controller, make_server


class ServiceBase(unittest.TestCase):
    """Un service réel sur un port libre ; son journal est gardé dans `self.journal` plutôt que d'encombrer les tests."""

    def setUp(self):
        self.journal = io.StringIO()
        silence = contextlib.redirect_stdout(self.journal)
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.controleur = Controller(collecte_url=None, out_dir=self.dossier.name)
        self.serveur = make_server(0, "127.0.0.1", self.controleur)
        fil = threading.Thread(target=self.serveur.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        fil.start()
        self.addCleanup(fil.join, 5)
        self.addCleanup(self.serveur.server_close)
        self.addCleanup(self.serveur.shutdown)

    def appel(self, methode, chemin, corps=None, brut=None):
        connexion = http.client.HTTPConnection("127.0.0.1", self.serveur.server_address[1], timeout=10)
        donnees = brut if brut is not None else (json.dumps(corps).encode() if corps is not None else None)
        connexion.request(methode, chemin, body=donnees, headers={"Content-Type": "application/json"} if donnees else {})
        reponse = connexion.getresponse()
        texte = reponse.read()
        connexion.close()
        return reponse.status, json.loads(texte)

    def attendre(self, condition, delai=10.0):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            statut = self.appel("GET", "/api/v1/run")[1]
            if condition(statut):
                return statut
            time.sleep(0.02)
        self.fail(f"condition jamais remplie : {self.appel('GET', '/api/v1/run')[1]}")



class ServiceHttp(ServiceBase):
    # --- inchangé depuis la première version du simulateur (MS-06) ---------------------------------------------
    def test_la_sonde_repond_comme_celle_des_services(self):
        statut, corps = self.appel("GET", "/api/v1/health")
        self.assertEqual(statut, 200)
        self.assertEqual(set(corps), {"status", "version", "revision", "environment"})
        self.assertEqual(corps["status"], "ok")

    def test_une_route_inconnue_est_introuvable(self):
        self.assertEqual(self.appel("GET", "/autre"), (404, {"detail": "introuvable"}))

    def test_une_methode_non_permise_donne_405(self):
        self.assertEqual(self.appel("DELETE", "/api/v1/health")[0], 405)
        self.assertEqual(self.appel("GET", "/api/v1/anomalies")[0], 405)

    def test_les_scenarios_se_listent(self):
        statut, corps = self.appel("GET", "/api/v1/scenarios")
        self.assertEqual(statut, 200)
        self.assertEqual([s["scenario_id"] for s in corps["scenarios"]], ["journee-calme", "heure-de-pointe", "incident-ponctuel"])

    # --- runs --------------------------------------------------------------------------------------------------
    def test_un_run_sans_destination_se_deroule_jusqu_au_bout(self):
        statut, corps = self.appel("POST", "/api/v1/run", {"scenario": "heure-de-pointe", "seed": 7, "duration": "1m", "sink": "aucun"})
        self.assertEqual(statut, 202)
        fini = self.attendre(lambda s: s["state"] == "finished")
        self.assertEqual((fini["run_id"], fini["seed"], fini["intervals_done"], fini["intervals_total"]), ("run-heure-de-pointe-7", 7, 6, 6))

    def test_un_run_en_fichier_ecrit_le_dossier_complet(self):
        self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": "1m", "sink": "fichier", "run_id": "run-essai"})
        self.attendre(lambda s: s["state"] == "finished")
        dossier = Path(self.dossier.name) / "run-essai"
        self.assertEqual(sorted(p.name for p in dossier.iterdir()), ["manifest.json", "mesures.jsonl", "verite-terrain.jsonl"])
        self.assertEqual(len((dossier / "mesures.jsonl").read_text(encoding="utf-8").splitlines()), 144)

    def test_les_anomalies_programmees_au_lancement_sont_appliquees(self):
        self.appel("POST", "/api/v1/run", {"scenario": "heure-de-pointe", "duration": "2m", "sink": "fichier", "run_id": "run-prog",
                                           "start": "2026-10-20T07:30:00Z",
                                           "anomalies": [{"kind": "muet", "sensor": "SENSOR_007", "at": "+20", "duration": "30s"}]})
        self.attendre(lambda s: s["state"] == "finished")
        verite = [json.loads(ligne) for ligne in (Path(self.dossier.name) / "run-prog" / "verite-terrain.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len([r for r in verite if not r["emitted"]]), 3)

    def test_un_seul_run_a_la_fois(self):
        self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": "10m", "rate": 50, "sink": "aucun"})
        self.addCleanup(self.controleur.stop)
        statut, corps = self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "sink": "aucun"})
        self.assertEqual(statut, 409)
        self.assertIn("déjà en cours", corps["detail"])

    def test_arreter_un_run(self):
        self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": "10m", "rate": 50, "sink": "aucun"})
        self.attendre(lambda s: s["delivered"] > 0)
        statut, corps = self.appel("DELETE", "/api/v1/run")
        self.assertEqual((statut, corps["state"]), (200, "stopped"))
        self.assertLess(corps["intervals_done"], corps["intervals_total"])
        self.assertEqual(self.appel("DELETE", "/api/v1/run")[0], 409)

    def test_le_debit_demande_est_applique(self):
        self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": "10m", "rate": 100, "sink": "aucun"})
        self.addCleanup(self.controleur.stop)
        debut = time.monotonic()
        self.attendre(lambda s: s["delivered"] >= 100)
        self.assertGreaterEqual(time.monotonic() - debut, 0.9)  # 100 messages à 100 par seconde : au moins ~1 s
        self.assertEqual(self.appel("GET", "/api/v1/run")[1]["rate"], 100.0)

    def test_collecte_sans_adresse_est_une_erreur_claire(self):
        statut, corps = self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "sink": "collecte"})
        self.assertEqual(statut, 400)
        self.assertIn("COLLECTE_URL", corps["detail"])

    def test_les_requetes_invalides_donnent_400(self):
        for corps, fragment in (
            ({"scenario": "inconnu"}, "scénario inconnu"),
            ({"scenario": "journee-calme", "rate": -1, "sink": "aucun"}, "rate"),
            ({"scenario": "journee-calme", "sink": "nulle-part"}, "destination inconnue"),
            ({"scenario": "journee-calme", "duration": "longtemps", "sink": "aucun"}, "durée illisible"),
            ({"scenario": "journee-calme", "seed": -3, "sink": "aucun"}, "graine"),
            ({"scenario": "journee-calme", "sink": "aucun", "anomalies": [{"kind": "muet", "sensor": "SENSOR_999"}]}, "capteur inconnu"),
        ):
            with self.subTest(corps=corps):
                statut, reponse = self.appel("POST", "/api/v1/run", corps)
                self.assertEqual(statut, 400)
                self.assertIn(fragment, reponse["detail"])
        self.assertEqual(self.appel("POST", "/api/v1/run", brut=b"{pas du json")[0], 400)
        self.assertEqual(self.appel("POST", "/api/v1/run", brut=b"[1, 2]")[0], 400)

    # --- anomalies à la demande --------------------------------------------------------------------------------
    def test_sans_run_en_cours_pas_d_injection(self):
        statut, corps = self.appel("POST", "/api/v1/anomalies", {"kind": "muet", "sensor": "SENSOR_001"})
        self.assertEqual(statut, 409)
        self.assertIn("aucun run", corps["detail"])

    def test_une_anomalie_injectee_pendant_le_run_touche_le_prochain_intervalle_et_rien_avant(self):
        self.appel("POST", "/api/v1/run", {"scenario": "heure-de-pointe", "start": "2026-10-20T07:30:00Z", "duration": "10m",
                                           "rate": 240, "sink": "fichier", "run_id": "run-demande"})
        self.attendre(lambda s: s["intervals_done"] >= 3)
        statut, corps = self.appel("POST", "/api/v1/anomalies", {"kind": "aberrante", "sensor": "SENSOR_003", "variant": "vitesse"})
        self.assertEqual(statut, 202)
        debut = corps["anomaly"]["start"]
        self.assertTrue(debut.endswith("0Z") and debut > "2026-10-20T07:30:20Z")
        # Arrêter seulement une fois l'intervalle annoncé traité (sinon l'anomalie n'a rien touché : le run s'arrête avant).
        format_utc = "%Y-%m-%dT%H:%M:%SZ"
        indice = int((datetime.strptime(debut, format_utc) - datetime.strptime("2026-10-20T07:30:00Z", format_utc)).total_seconds() // 10)
        self.attendre(lambda s: s["intervals_done"] >= indice + 2)
        self.appel("DELETE", "/api/v1/run")
        verite = [json.loads(ligne) for ligne in (Path(self.dossier.name) / "run-demande" / "verite-terrain.jsonl").read_text(encoding="utf-8").splitlines()]
        marquees = [(r["time"], r["sensor_id"]) for r in verite if r["anomalies"]]
        self.assertEqual(marquees, [(debut, "SENSOR_003")])  # un seul intervalle, celui annoncé, et pas un de plus
        manifeste = json.loads((Path(self.dossier.name) / "run-demande" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([a["start"] for a in manifeste["anomalies"]], [debut])  # le manifeste permet de rejouer le run
        self.assertLess(manifeste["intervals_played"], manifeste["intervals"])  # un run arrêté le dit

    def test_chaque_type_d_anomalie_est_accepte_a_la_demande(self):
        self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": "10m", "rate": 100, "sink": "aucun"})
        self.addCleanup(self.controleur.stop)
        for corps in ({"kind": "aberrante", "sensor": "SENSOR_001", "variant": "debit"}, {"kind": "muet", "sensor": "SENSOR_002", "duration": "1m"},
                      {"kind": "doublon", "sensor": "SENSOR_003", "copies": 2}, {"kind": "retard", "sensor": "SENSOR_004", "delay": 40}):
            with self.subTest(corps=corps):
                statut, reponse = self.appel("POST", "/api/v1/anomalies", corps)
                self.assertEqual(statut, 202)
                self.assertEqual(reponse["anomaly"]["kind"], corps["kind"])
        self.assertEqual(len(self.appel("GET", "/api/v1/run")[1]["anomalies"]), 4)

    def test_une_anomalie_mal_formee_ou_dans_le_passe_est_refusee(self):
        self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "start": "2026-10-20T00:00:00Z", "duration": "10m", "rate": 100, "sink": "aucun"})
        self.addCleanup(self.controleur.stop)
        self.attendre(lambda s: s["intervals_done"] >= 2)
        for corps, fragment in (({"kind": "inconnue", "sensor": "SENSOR_001"}, "type d'anomalie inconnu"),
                                ({"kind": "muet", "sensor": "SENSOR_999"}, "capteur inconnu"),
                                ({"kind": "muet", "sensor": "SENSOR_001", "at": "2026-10-20T00:00:10Z"}, "passé"),
                                ({"kind": "muet", "sensor": "SENSOR_001", "couleur": "rouge"}, "champ inconnu")):
            with self.subTest(corps=corps):
                statut, reponse = self.appel("POST", "/api/v1/anomalies", corps)
                self.assertEqual(statut, 400)
                self.assertIn(fragment, reponse["detail"])


if __name__ == "__main__":
    unittest.main()
