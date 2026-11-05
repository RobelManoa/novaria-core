"""Aléa sans état et réseau fixe : ce sur quoi repose tout le reste."""

import re
import statistics
import unittest

from helpers import ROOT

from novaria_sim import rng
from novaria_sim.network import INTERVAL_S, SEGMENT_BY_SENSOR, SEGMENTS, SENSOR_IDS

MIGRATION = (ROOT / "db" / "postgres" / "migrations" / "0005_reseau_demo.sql").read_text(encoding="utf-8")


class Alea(unittest.TestCase):
    def test_une_valeur_ne_depend_que_de_la_graine_et_de_la_cle(self):
        self.assertEqual(rng.uniform(42, "a", 1), rng.uniform(42, "a", 1))
        self.assertNotEqual(rng.uniform(42, "a", 1), rng.uniform(43, "a", 1))
        self.assertNotEqual(rng.uniform(42, "a", 1), rng.uniform(42, "a", 2))

    def test_valeurs_epinglees_donc_identiques_sur_toute_machine_et_toute_version_de_python(self):
        # Recalculées avec un code indépendant de rng.py (BLAKE2b, 8 octets, 53 bits de poids fort ; somme de 6 tirages
        # pour la loi normale). BLAKE2b et additions seulement : si ces valeurs changent, les runs déjà produits ne se rejouent plus.
        self.assertEqual(rng.uniform(42, "a", 0), 0.22102884633376418)
        self.assertEqual(rng.uniform(0, "count", "SENSOR_001", 1792483210), 0.41907264059183347)
        self.assertEqual(rng.normal(42, "x"), 0.38954037117042667)

    def test_le_tirage_reste_dans_zero_un_exclu(self):
        values = [rng.uniform(7, "k", i) for i in range(20000)]
        self.assertTrue(all(0.0 <= value < 1.0 for value in values))
        self.assertAlmostEqual(statistics.mean(values), 0.5, delta=0.01)

    def test_la_loi_normale_est_centree_reduite(self):
        values = [rng.normal(7, "k", i) for i in range(20000)]
        self.assertAlmostEqual(statistics.mean(values), 0.0, delta=0.03)
        self.assertAlmostEqual(statistics.pstdev(values), 1.0, delta=0.03)

    def test_poisson_a_la_bonne_esperance(self):
        for rate in (0.4, 1.5, 3.9, 12.0):
            counts = [rng.poisson(rng.uniform(1, "p", i), rate) for i in range(8000)]
            with self.subTest(rate=rate):
                self.assertAlmostEqual(statistics.mean(counts), rate, delta=0.1 * max(rate, 1))

    def test_poisson_aux_bornes(self):
        self.assertEqual(rng.poisson(0.99, 0), 0)
        self.assertEqual(rng.poisson(0.5, -1), 0)
        with self.assertRaises(ValueError):
            rng.poisson(0.5, 501)


class Reseau(unittest.TestCase):
    def test_six_carrefours_vingt_quatre_troncons_vingt_quatre_capteurs(self):
        self.assertEqual(len({segment.intersection_id for segment in SEGMENTS}), 6)
        self.assertEqual(len(SEGMENTS), 24)
        self.assertEqual(len(SENSOR_IDS), 24)
        self.assertEqual(len(set(SENSOR_IDS)), 24)

    def test_un_capteur_par_troncon_dans_le_meme_ordre(self):
        for segment in SEGMENTS:
            self.assertEqual(segment.sensor_id.split("_")[1], segment.road_segment_id.split("_")[1])
        self.assertEqual(SEGMENT_BY_SENSOR["SENSOR_005"].road_segment_id, "ROAD_005")

    def test_les_troncons_sont_ceux_de_la_migration_0005(self):
        pattern = re.compile(r"\('(ROAD_\d+)', '(INT_\d+)', '[^']*', '([NESW])', '(\w+)', (\d+), (\d+), (\d+)\)")
        attendus = [(r, i, a, t, int(l), int(m), int(v)) for r, i, a, t, l, m, v in pattern.findall(MIGRATION)]
        obtenus = [(s.road_segment_id, s.intersection_id, s.approach, s.road_type, s.lane_count, s.length_m, s.speed_limit_kmh)
                   for s in SEGMENTS]
        self.assertEqual(len(attendus), 24)
        self.assertEqual(obtenus, attendus)

    def test_les_capteurs_sont_ceux_de_la_migration_0005(self):
        attendus = re.findall(r"\('(SENSOR_\d+)', '(ROAD_\d+)'\)", MIGRATION)
        self.assertEqual([(s.sensor_id, s.road_segment_id) for s in SEGMENTS], attendus)

    def test_une_mesure_toutes_les_10_secondes_comme_la_migration(self):
        self.assertEqual(INTERVAL_S, 10)
        self.assertIn("'SIMULATED', 10", MIGRATION)  # dim_sensor.reporting_interval_s

    def test_la_vitesse_fluide_est_la_vitesse_limite(self):
        self.assertTrue(all(s.free_flow_speed_kmh == s.speed_limit_kmh for s in SEGMENTS))


if __name__ == "__main__":
    unittest.main()
