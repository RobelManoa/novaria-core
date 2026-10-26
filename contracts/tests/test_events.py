"""Tests des contrats d'événements (contracts/events). Lancer :
    python3 -m unittest discover -s contracts/tests -v        (Windows : py -3 -m unittest ...)
Dépendances : pip install jsonschema referencing
"""
import sys
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_events as ve  # noqa: E402
from cases import EXAMPLES, INVALID_CASES, load, mutate  # noqa: E402


class SchemasTests(unittest.TestCase):
    def test_chaque_schema_est_un_schema_valide(self):
        from jsonschema import Draft202012Validator
        for name, schema in ve._SCHEMAS.items():
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(schema)

    def test_chaque_type_a_son_schema_et_un_exemple(self):
        for event_type, schema_name in ve.SCHEMA_BY_TYPE.items():
            self.assertIn(schema_name, ve._SCHEMAS)
            self.assertTrue(any(load(p.name)["type"] == event_type for p in EXAMPLES.glob("*.json")),
                            f"aucun exemple pour {event_type}")

    def test_les_exemples_sont_valides(self):
        files = sorted(EXAMPLES.glob("*.json"))
        self.assertGreaterEqual(len(files), 17)
        for path in files:
            with self.subTest(exemple=path.name):
                self.assertEqual(ve.validate_event(load(path.name)), [])


class InvalidEventsTests(unittest.TestCase):
    def test_chaque_cas_invalide_est_refuse_pour_la_bonne_raison(self):
        for description, example, change, fragment in INVALID_CASES:
            with self.subTest(cas=description):
                errors = ve.validate_event(mutate(example, change))
                self.assertTrue(errors, "l'événement aurait dû être refusé")
                self.assertTrue(any(fragment in message for message in errors), f"{fragment!r} absent de {errors}")

    def test_les_champs_facultatifs_peuvent_manquer(self):
        event = mutate("mesure-valide.json", lambda e: (e.pop("correlation_id"), e["data"].pop("queue_length_m")))
        self.assertEqual(ve.validate_event(event), [])

    def test_fichier_illisible_donne_le_code_2(self):
        with unittest.mock.patch("sys.stderr"):
            self.assertEqual(ve.main(["fichier-qui-n-existe-pas.json"]), 2)


if __name__ == "__main__":
    unittest.main()
