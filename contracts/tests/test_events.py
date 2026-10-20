"""Tests des contrats d'événements (contracts/events). Lancer :
    python3 -m unittest discover -s contracts/tests -v        (Windows : py -3 -m unittest ...)
Dépendances : pip install jsonschema referencing
"""
import copy
import json
import sys
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import validate_events as ve  # noqa: E402

EXAMPLES = ROOT / "events" / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


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
        self.assertGreaterEqual(len(files), 9)
        for path in files:
            with self.subTest(exemple=path.name):
                self.assertEqual(ve.validate_event(load(path.name)), [])


def mutate(name, change):
    event = copy.deepcopy(load(name))
    change(event)
    return event


# (description, exemple de départ, modification, fragment attendu dans le message d'erreur)
INVALID_CASES = [
    ("champ inconnu dans l'enveloppe", "mesure-valide.json", lambda e: e.update(extra=1), "extra"),
    ("champ inconnu dans data", "mesure-valide.json", lambda e: e["data"].update(vitesse_mph=30), "vitesse_mph"),
    ("type inconnu", "mesure-valide.json", lambda e: e.update(type="novaria.autre.v1"), "type inconnu"),
    ("date sans fuseau", "mesure-valide.json", lambda e: e.update(time="2026-10-20T08:00:10"), "does not match"),
    ("date avec décalage au lieu de UTC", "mesure-valide.json", lambda e: e.update(time="2026-10-20T10:00:10+02:00"), "does not match"),
    ("identifiant de carrefour mal formé", "mesure-valide.json", lambda e: e.update(subject="carrefour-1"), "does not match"),
    ("vitesse négative", "mesure-valide.json", lambda e: e["data"].update(average_speed_kmh=-1), "minimum"),
    ("vitesse hors borne (200 km/h)", "mesure-valide.json", lambda e: e["data"].update(average_speed_kmh=250), "maximum"),
    ("taux d'occupation supérieur à 1", "mesure-valide.json", lambda e: e["data"].update(occupancy_rate=1.4), "maximum"),
    ("nombre de véhicules fractionnaire", "mesure-valide.json", lambda e: e["data"].update(vehicle_count=2.5), "integer"),
    ("vitesse présente alors qu'aucun véhicule", "mesure-route-vide.json", lambda e: e["data"].update(average_speed_kmh=30), "null"),
    ("mesure VALID sans vitesse malgré des véhicules", "mesure-valide.json", lambda e: e["data"].update(average_speed_kmh=None), "number"),
    ("mesure VALID sans taux d'occupation", "mesure-valide.json", lambda e: e["data"].update(occupancy_rate=None), "number"),
    ("statut de qualité inconnu", "mesure-valide.json", lambda e: e["data"]["quality"].update(status="GOOD"), "GOOD"),
    ("drapeau de qualité inconnu", "mesure-partielle.json", lambda e: e["data"]["quality"].update(flags=["BIZARRE"]), "BIZARRE"),
    ("provenance absente", "mesure-valide.json", lambda e: e["data"].pop("provenance"), "provenance"),
    ("simulation sans graine", "mesure-valide.json", lambda e: e["data"]["provenance"].pop("seed"), "seed"),
    ("simulation sans scénario", "mesure-valide.json", lambda e: e["data"]["provenance"].pop("scenario_id"), "scenario_id"),
    ("origine historique sans jeu de données", "mesure-valide.json",
     lambda e: e["data"]["provenance"].update(source_type="REAL_HISTORICAL"), "dataset_id"),
    ("origine inconnue", "mesure-valide.json", lambda e: e["data"]["provenance"].update(source_type="IMAGINARY"), "IMAGINARY"),
    ("fenêtre de 2 minutes", "indicateur-fluide.json", lambda e: e["data"].update(window_size_s=120), "120"),
    ("état de congestion inconnu", "indicateur-fluide.json", lambda e: e["data"].update(congestion_state="JAMMED"), "JAMMED"),
    ("ratio de vitesse non nul sans vitesse", "indicateur-route-vide.json", lambda e: e["data"].update(speed_ratio=0.5), "null"),
    ("congestion sans ratio de vitesse", "indicateur-congestion.json", lambda e: e["data"].update(speed_ratio=None), "number"),
    ("mesures attendues à zéro", "indicateur-fluide.json", lambda e: e["data"].update(expected_sample_count=0), "minimum"),
    ("alerte résolue sans date de résolution", "alerte-resolue.json", lambda e: e["data"].update(resolved_at=None), "string"),
    ("alerte non résolue avec une date de résolution", "alerte-creee.json",
     lambda e: e["data"].update(resolved_at="2026-10-20T09:00:00Z"), "null"),
    ("alerte non résolue avec un mode de résolution", "alerte-creee.json", lambda e: e["data"].update(resolution="AUTO"), "null"),
    ("état d'alerte inconnu", "alerte-creee.json", lambda e: e["data"].update(state="CLOSED"), "CLOSED"),
    ("identifiant d'alerte qui n'est pas un UUID", "alerte-creee.json", lambda e: e["data"].update(alert_id="abc"), "uuid"),
    # Règles sémantiques (comparaison entre champs)
    ("subject différent du carrefour de data", "mesure-valide.json", lambda e: e.update(subject="INT_02"), "subject"),
    ("id de mesure qui ne suit pas la convention", "mesure-valide.json", lambda e: e.update(id="n-importe-quoi"), "id de mesure"),
    ("fenêtre non alignée", "indicateur-fluide.json",
     lambda e: (e["data"].update(window_start="2026-10-20T08:00:07Z"), e.update(time="2026-10-20T08:01:07Z")), "aligné"),
    ("time d'un indicateur différent de la fin de fenêtre", "indicateur-fluide.json", lambda e: e.update(time="2026-10-20T08:00:00Z"), "fin de fenêtre"),
    ("alerte résolue avant d'être ouverte", "alerte-resolue.json", lambda e: e["data"].update(resolved_at="2026-10-20T08:00:00Z"), "précéder"),
]


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
