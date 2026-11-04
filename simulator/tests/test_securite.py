"""Sécurité du simulateur, dans l'esprit de docs/04-devsecops/securite-applicative.md (BE-08) : chemins, journal, bornes."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import START, config

from novaria_sim.anomalies import parse_spec
from novaria_sim.cli import main
from novaria_sim.run import Run, RunConfig
from test_service import ServiceBase


class IdentifiantDeRun(unittest.TestCase):
    def test_un_identifiant_fait_de_points_seuls_est_refuse(self):
        for mauvais in (".", "..", "...", "...."):
            with self.subTest(run_id=mauvais), self.assertRaisesRegex(ValueError, "run_id"):
                RunConfig(mauvais, "heure-de-pointe", 42, START, START.replace(minute=40))

    def test_les_identifiants_ordinaires_restent_acceptes(self):
        for bon in ("run-1", "run_1.2", "pointe.42", ".cache", "a" * 80, "RUN-A.b_c"):
            with self.subTest(run_id=bon):
                RunConfig(bon, "heure-de-pointe", 42, START, START.replace(minute=40))

    def test_les_identifiants_dangereux_sont_refuses(self):
        for mauvais in ("a/b", "a\\b", "a:b", "a b", "../x", "", "a" * 81, "é", "a\nb", "a\x00b"):
            with self.subTest(run_id=repr(mauvais)), self.assertRaises(ValueError):
                RunConfig(mauvais, "heure-de-pointe", 42, START, START.replace(minute=40))

    def test_la_ligne_de_commande_refuse_aussi_les_points_seuls(self):
        sortie, erreur = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            code = main(["run", "--scenario", "journee-calme", "--run-id", "..", "--duration", "1m", "--stdout"])
        self.assertEqual((code, sortie.getvalue()), (2, ""))
        self.assertIn("run_id", erreur.getvalue())


class ServiceSecurise(ServiceBase):
    def test_un_run_en_fichier_n_ecrit_jamais_hors_du_dossier_prevu(self):
        sentinelle = Path(self.dossier.name).parent  # le parent du dossier de sortie : c'est là que « .. » écrirait
        avant = set(sentinelle.iterdir())
        for mauvais in ("..", ".", "../evasion"):
            with self.subTest(run_id=mauvais):
                statut, corps = self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": "1m", "sink": "fichier", "run_id": mauvais})
                self.assertEqual(statut, 400)
                self.assertIn("run_id", corps["detail"])
        self.assertEqual(set(sentinelle.iterdir()), avant)
        self.assertEqual(list(Path(self.dossier.name).iterdir()), [])

    def test_le_journal_n_ecrit_jamais_la_query_string(self):
        self.appel("GET", "/api/v1/health?token=SECRET-DANS-L-ADRESSE&mot_de_passe=hunter2")
        self.appel("GET", "/api/v1/run?jeton=AUTRE-SECRET")
        texte = self.journal.getvalue()
        for interdit in ("SECRET-DANS-L-ADRESSE", "hunter2", "AUTRE-SECRET", "token", "mot_de_passe", "jeton", "?"):
            self.assertNotIn(interdit, texte)
        lignes = [json.loads(ligne)["message"] for ligne in texte.splitlines()]
        self.assertTrue(any("GET /api/v1/health" in ligne and " 200" in ligne for ligne in lignes))  # l'essentiel reste lisible

    def test_le_corps_d_une_requete_n_est_jamais_journalise(self):
        self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "sink": "aucun", "run_id": "CORPS-DISCRET", "duration": "1m"})
        self.attendre(lambda s: s["state"] == "finished")
        self.assertNotIn("CORPS-DISCRET", self.journal.getvalue())

    def test_une_duree_demesuree_est_refusee(self):
        for duree, accepte in (("1000h", False), ("604810", False), ("604800", True)):  # 7 jours = 604 800 s
            with self.subTest(duree=duree):
                statut, corps = self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": duree, "sink": "aucun", "rate": 1})
                if accepte:
                    self.assertEqual(statut, 202)
                    self.appel("DELETE", "/api/v1/run")
                else:
                    self.assertEqual(statut, 400)
                    self.assertIn("durée", corps["detail"])

    def test_un_debit_demesure_est_refuse(self):
        statut, corps = self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": "1m", "sink": "aucun", "rate": 1_000_001})
        self.assertEqual(statut, 400)
        self.assertIn("rate", corps["detail"])

    def test_trop_d_anomalies_au_lancement_sont_refusees(self):
        anomalies = [{"kind": "doublon", "sensor": "SENSOR_001", "at": f"+{10 * i}"} for i in range(1, 102)]
        statut, corps = self.appel("POST", "/api/v1/run", {"scenario": "journee-calme", "duration": "1h", "sink": "aucun", "anomalies": anomalies})
        self.assertEqual(statut, 400)
        self.assertIn("anomalies", corps["detail"])

    def test_un_corps_trop_grand_est_refuse(self):
        statut, corps = self.appel("POST", "/api/v1/run", brut=b'{"scenario":"' + b"a" * (70 * 1024) + b'"}')
        self.assertEqual(statut, 413)


class NombreDAnomalies(unittest.TestCase):
    def test_un_run_refuse_plus_de_mille_anomalies(self):
        run = Run(config(minutes=10))
        for i in range(1000):
            run.add_anomaly(parse_spec(f"doublon:sensor=SENSOR_001,at=+{10 * (i % 59 + 1)}", START))
        with self.assertRaisesRegex(ValueError, "1000"):
            run.add_anomaly(parse_spec("doublon:sensor=SENSOR_001,at=+10", START))
        self.assertEqual(len(run.anomalies), 1000)


if __name__ == "__main__":
    unittest.main()
