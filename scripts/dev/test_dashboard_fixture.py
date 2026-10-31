"""Tests de scripts/dev/dashboard_fixture.py (sans réseau : l'API est simulée) et de la fixture du tableau de bord (FE-04).

Lancer :  python3 -m unittest discover -s scripts/dev -p "test_dashboard_fixture.py" -v
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dashboard_fixture as fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FILE = ROOT / "frontend" / "tests" / "fixtures" / "dashboard-api.json"


def row(segment="ROAD_001", start="2026-10-20T08:00:00Z", count=0, speed=None, flow=0.0, state="FREE_FLOW", run="run-1"):
    return {
        "indicator_id": f"{run}:{segment}:60:{start}", "road_segment_id": segment, "intersection_id": "INT_01",
        "window_start": start, "window_size_s": 60, "vehicle_count": count, "flow_veh_per_min": flow,
        "average_speed_kmh": speed, "congestion_state": state,
        "provenance": {"source_type": "SIMULATED", "run_id": run, "scenario_id": "demo", "seed": 1},
    }


class ArrondiTests(unittest.TestCase):
    def test_arrondit_la_valeur_binaire_exacte_moitie_vers_le_haut(self):
        self.assertEqual(fixture.fixed(0.25, 1), "0.3")  # 0,25 est exact en binaire : moitié vers le haut
        self.assertEqual(fixture.fixed(2.675, 2), "2.67")  # 2,675 vaut 2,67499… en binaire
        self.assertEqual(fixture.fixed(28.55, 1), "28.6")  # 28,55 vaut 28,5500000000000007 en binaire
        self.assertEqual(fixture.fixed(16171, 0), "16171")
        self.assertIsNone(fixture.fixed(None, 1))


class ValeursAttenduesTests(unittest.TestCase):
    def test_aucun_indicateur_donne_aucune_valeur(self):
        self.assertIsNone(fixture.expected_values([]))

    def test_meme_jeu_que_le_test_du_front_end(self):
        # Mêmes données et mêmes résultats que tests/features/dashboard/summary.test.ts : deux langages, un résultat.
        expected = fixture.expected_values([
            row(start="2026-10-20T08:01:00Z", count=4, speed=40, flow=4),
            row(start="2026-10-20T08:00:00Z", count=2, speed=30, flow=2),
            row("ROAD_002", "2026-10-20T08:00:00Z", count=6, speed=50, flow=6),
        ])
        self.assertEqual(expected["speed_series"], [["2026-10-20T08:00:00Z", "45.0"], ["2026-10-20T08:01:00Z", "40.0"]])
        self.assertEqual(expected["flow_series"], [["2026-10-20T08:00:00Z", "8.0"], ["2026-10-20T08:01:00Z", "4.0"]])
        self.assertEqual(expected["cards"]["flow"], "6.0")  # (8 + 4) / 2 fenêtres
        self.assertEqual(expected["cards"]["vehicles"], "12")

    def test_la_vitesse_est_ponderee_par_les_vehicules(self):
        expected = fixture.expected_values([row(count=10, speed=60), row("ROAD_002", count=30, speed=20)])
        self.assertEqual(expected["cards"]["speed"], "30.0")  # une moyenne simple donnerait 40

    def test_les_etats_comptent_la_derniere_fenetre_de_chaque_troncon(self):
        expected = fixture.expected_values([
            row(start="2026-10-20T08:00:00Z", state="FREE_FLOW"),
            row(start="2026-10-20T08:02:00Z", state="CONGESTED"),
            row(start="2026-10-20T08:01:00Z", state="SLOW"),
            row("ROAD_002", state="FREE_FLOW"),
            row("ROAD_003", state="UNKNOWN"),
        ])
        self.assertEqual(expected["states"], {"CONGESTED": 1, "SLOW": 0, "FREE_FLOW": 1, "UNKNOWN": 1})
        self.assertEqual(expected["cards"]["congested"], "1 sur 3")
        self.assertEqual([item["road_segment_id"] for item in expected["segments"]], ["ROAD_001", "ROAD_002", "ROAD_003"])

    def test_une_fenetre_sans_vitesse_n_est_pas_un_zero(self):
        expected = fixture.expected_values([row(count=0, speed=None)])
        self.assertIsNone(expected["cards"]["speed"])
        self.assertEqual(expected["segments"][0]["speed"], None)


class CollecteTests(unittest.TestCase):
    def test_les_appels_sont_ceux_du_tableau_de_bord(self):
        newest = {"items": [row(start="2026-10-30T08:55:00Z", run="run-9")], "next_cursor": "x"}
        pages = [{"items": [row(start="2026-10-30T08:55:00Z", run="run-9")], "next_cursor": None}]
        answers = [newest, *pages]
        seen = []

        def fake_get(api, path, query, token):
            seen.append(query)
            return answers[len(seen) - 1]

        scenario = {"period_hours": 6, "window_size_s": 60, "intersection_id": "INT_03"}
        with mock.patch.object(fixture, "api_get", fake_get):
            calls, indicators = fixture.collect("http://api", "jeton", scenario)

        self.assertEqual(seen[0], {"intersection_id": "INT_03", "window_size_s": "60", "limit": "1"})
        # Même arithmétique que tests/features/dashboard/load.test.ts : fin à 08:56 (borne exclue), départ 6 h avant.
        self.assertEqual(seen[1], {
            "intersection_id": "INT_03", "window_size_s": "60", "run_id": "run-9",
            "from": "2026-10-30T02:56:00Z", "to": "2026-10-30T08:56:00Z", "limit": "500"})
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(indicators), 1)

    def test_sans_donnee_un_seul_appel(self):
        with mock.patch.object(fixture, "api_get", return_value={"items": [], "next_cursor": None}) as get:
            calls, indicators = fixture.collect("http://api", "jeton", {"period_hours": 1, "window_size_s": 60, "intersection_id": None})
        self.assertEqual(get.call_count, 1)
        self.assertEqual((len(calls), indicators), (1, []))

    def test_suit_les_curseurs(self):
        first = {"items": [row(start="2026-10-30T08:55:00Z")], "next_cursor": "c1"}
        second = {"items": [row("ROAD_002", "2026-10-30T08:55:00Z")], "next_cursor": None}
        with mock.patch.object(fixture, "api_get", side_effect=[first, first, second]) as get:
            _, indicators = fixture.collect("http://api", "jeton", {"period_hours": 1, "window_size_s": 60, "intersection_id": None})
        self.assertEqual(get.call_args_list[2].args[2]["cursor"], "c1")
        self.assertEqual(len(indicators), 2)


class LigneDeCommandeTests(unittest.TestCase):
    def test_refuse_une_adresse_qui_n_est_pas_http(self):
        with redirect_stderr(io.StringIO()) as erreur:
            code = fixture.main(["--api", "file:///etc/passwd", "--user", "x"])
        self.assertEqual(code, 1)
        self.assertIn("http", erreur.getvalue())


@unittest.skipUnless(FIXTURE_FILE.exists(), "fixture du front-end absente")
class FixtureEnregistreeTests(unittest.TestCase):
    """Le fichier lu par les tests du front-end est cohérent avec le calcul de ce script."""

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))

    def test_aucun_secret_dans_la_fixture(self):
        text = FIXTURE_FILE.read_text(encoding="utf-8").lower()
        for mot in ("access_token", "password", "bearer", "authorization"):
            self.assertNotIn(mot, text)

    def test_taille_raisonnable_et_une_seule_ligne(self):
        self.assertLess(FIXTURE_FILE.stat().st_size, 1_000_000)  # jamais de jeu de plus de 1 Mo dans le dépôt

    def test_donnees_simulees_dites_comme_telles(self):
        for scenario in self.data["scenarios"]:
            if scenario["expected"]:
                self.assertEqual(scenario["expected"]["meta"]["source_type"], "SIMULATED")

    def test_les_valeurs_attendues_sont_celles_recalculees_sur_les_reponses_enregistrees(self):
        for scenario in self.data["scenarios"]:
            lecture = [r["response"]["items"] for r in scenario["requests"][1:]]
            indicators = [item for page in lecture for item in page]
            self.assertEqual(fixture.expected_values(indicators), scenario["expected"], scenario["name"])


if __name__ == "__main__":
    unittest.main()
