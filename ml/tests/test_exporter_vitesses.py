"""L'export d'un réseau de vitesses pour l'entrepôt (IA-16) : seules les vitesses mesurées, le bon format, rien d'inventé."""

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tests import support  # noqa: F401  (chemins d'import)

NUMPY = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(NUMPY, "numpy absent (ml/.venv)")
class Export(unittest.TestCase):
    def serie(self):
        import numpy as np

        from prevision.donnees import Serie

        debut = 1_338_508_800_000  # 2012-06-01T00:00:00 (heure murale lue comme UTC)
        instants = debut + np.arange(6, dtype=np.int64) * 300_000
        vitesses = np.array([[60.0, np.nan], [61.5, 40.0], [np.nan, np.nan], [58.0, 41.25], [57.0, np.nan], [56.0, 42.0]])
        return Serie("essai", instants, ("111", "222"), vitesses)

    def test_seules_les_vitesses_mesurees_sont_ecrites_au_format_du_chargeur(self):
        from prevision import exporter_vitesses

        with tempfile.TemporaryDirectory() as t:
            nombres = exporter_vitesses.ecrire(self.serie(), Path(t), "2012-06-01")
            lignes = list(csv.reader((Path(t) / "mesures.csv").open(encoding="utf-8")))
            manifeste = json.loads((Path(t) / "manifeste.json").read_text(encoding="utf-8"))
        self.assertEqual(lignes[0], ["observed_at", "sensor_id", "speed"])
        self.assertEqual(nombres, {"pas": 6, "capteurs": 2, "mesures": 8})
        self.assertEqual(len(lignes) - 1, 8)  # 12 cases, 4 absentes : pas de ligne pour une mesure absente
        self.assertIn(["2012-06-01T00:05:00Z", "222", "40.00"], lignes)
        self.assertNotIn("2012-06-01T00:10:00Z", {ligne[0] for ligne in lignes})  # un pas entièrement absent n'a aucune ligne
        self.assertEqual(manifeste["sensors"], ["111", "222"])
        self.assertEqual((manifeste["step_s"], manifeste["speed_unit"], manifeste["source_type"]), (300, "mph", "REAL_HISTORICAL"))

    def test_le_manifeste_et_les_mesures_passent_le_chargeur(self):
        import sys

        from prevision import exporter_vitesses
        from registre import format_arbres  # noqa: F401  (chemins d'import des tests)

        sys.path.insert(0, str(support.RACINE / "data" / "etl"))
        from pipelines import charger_vitesses as cv

        class Garde:
            def __init__(self):
                self.lignes = []

            def enregistrer(self, manifeste):
                self.manifeste = manifeste

            def charger(self, reseau, lot):
                self.lignes += lot
                return len(lot)

        with tempfile.TemporaryDirectory() as t:
            exporter_vitesses.ecrire(self.serie(), Path(t), "2012-06-01")
            garde = Garde()
            resultat = cv.charger_reseau(Path(t), entrepot=garde)
        self.assertEqual((resultat.lues, resultat.chargees, resultat.rejetees), (8, 8, 0))

    def test_une_date_apres_la_fin_des_donnees_est_refusee(self):
        from prevision import exporter_vitesses

        with tempfile.TemporaryDirectory() as t, self.assertRaisesRegex(ValueError, "aucun pas"):
            exporter_vitesses.ecrire(self.serie(), Path(t), "2012-06-02")


if __name__ == "__main__":
    unittest.main()
