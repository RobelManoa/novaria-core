"""Chaque message émis respecte le contrat MS-03 : schéma JSON ET règles entre champs, avec le validateur du dépôt."""

import json
import sys
import unittest
from datetime import UTC, datetime

from helpers import ROOT, config, play

from novaria_sim.anomalies import parse_spec
from novaria_sim.scenarios import SCENARIOS

sys.path.insert(0, str(ROOT / "contracts"))
try:
    from validate_events import validate_event
except ImportError:  # jsonschema absent : `pip install jsonschema referencing`
    validate_event = None

EXEMPLE = json.loads((ROOT / "contracts" / "events" / "examples" / "mesure-valide.json").read_text(encoding="utf-8"))

# Une fenêtre où il se passe quelque chose, par scénario
FENETRES = {
    "journee-calme": datetime(2026, 10, 20, 3, 0, tzinfo=UTC),
    "heure-de-pointe": datetime(2026, 10, 20, 7, 25, tzinfo=UTC),
    "incident-ponctuel": datetime(2026, 10, 20, 8, 5, tzinfo=UTC),
}
ANOMALIES = (
    "aberrante:sensor=SENSOR_003,at=+30,variant=vitesse",
    "aberrante:sensor=SENSOR_004,at=+30,variant=debit",
    "aberrante:sensor=SENSOR_009,at=+30,variant=vitesse-nulle",
    "aberrante:sensor=SENSOR_020,at=+30,variant=vitesse",
    "muet:sensor=SENSOR_007,at=+40,duration=60s",
    "doublon:sensor=SENSOR_001,at=+20,copies=3,lag=2",
    "retard:sensor=SENSOR_010,at=+50,delay=45",
)


@unittest.skipIf(validate_event is None, "jsonschema absent : pip install jsonschema referencing")
class Conformite(unittest.TestCase):
    def erreurs(self, deliveries):
        problemes = []
        for delivery in deliveries:
            problemes += [f"{delivery.event['id']} : {erreur}" for erreur in validate_event(delivery.event)]
        return problemes

    def test_tous_les_scenarios_donnent_des_messages_valides(self):
        for scenario, debut in FENETRES.items():
            with self.subTest(scenario=scenario):
                deliveries, _, _ = play(config(scenario, minutes=10, start=debut))
                self.assertEqual(len(deliveries), 24 * 60)
                self.assertEqual(self.erreurs(deliveries), [])

    def test_chaque_anomalie_donne_des_messages_valides_sur_chaque_scenario(self):
        for scenario, debut in FENETRES.items():
            anomalies = [parse_spec(spec, debut) for spec in ANOMALIES]
            with self.subTest(scenario=scenario):
                deliveries, _, _ = play(config(scenario, minutes=5, start=debut, anomalies=anomalies))
                self.assertEqual(self.erreurs(deliveries), [])

    def test_le_validateur_refuse_bien_un_message_abime(self):
        # Garde-fou : si le validateur acceptait tout, les tests ci-dessus ne prouveraient rien.
        message = play(config(minutes=1))[0][0].event
        for abime in (lambda m: m["data"].update(vehicle_count=-1), lambda m: m.update(id="mauvais-id"),
                      lambda m: m["data"].update(extra="x"), lambda m: m["data"]["quality"].update(status="SUSPECT")):
            copie = json.loads(json.dumps(message))
            abime(copie)
            with self.subTest(abime=abime):
                self.assertTrue(validate_event(copie))


class FormatEmis(unittest.TestCase):
    """Même forme que l'exemple du contrat, sans jsonschema."""

    def setUp(self):
        self.message = play(config(minutes=1))[0][0].event

    def test_memes_cles_dans_le_meme_ordre_que_l_exemple_du_contrat(self):
        self.assertEqual(list(self.message), list(EXEMPLE))
        self.assertEqual(list(self.message["data"]), list(EXEMPLE["data"]))
        self.assertEqual(list(self.message["data"]["provenance"]), list(EXEMPLE["data"]["provenance"]))

    def test_enveloppe(self):
        self.assertEqual(self.message["type"], "novaria.iot.measurement.v1")
        self.assertEqual(self.message["domain"], "iot")
        self.assertEqual(self.message["schema_version"], "1.0")
        self.assertEqual(self.message["source"], "simulateur/run-test")
        self.assertEqual(self.message["subject"], self.message["data"]["intersection_id"])

    def test_identifiant_run_capteur_instant_en_millisecondes(self):
        self.assertEqual(self.message["id"], "run-test:SENSOR_001:1792481410000")
        self.assertEqual(self.message["time"], "2026-10-20T07:30:10Z")
        self.assertEqual(self.message["correlation_id"], "corr-1792481410000")

    def test_provenance_simulee_avec_scenario_et_graine(self):
        self.assertEqual(self.message["data"]["provenance"],
                         {"source_type": "SIMULATED", "run_id": "run-test", "scenario_id": "heure-de-pointe", "seed": 42})

    def test_l_etat_de_congestion_voulu_n_est_jamais_dans_un_message(self):
        for scenario in SCENARIOS:
            for delivery in play(config(scenario, minutes=2))[0]:
                texte = json.dumps(delivery.event)
                self.assertNotIn("label", texte)
                self.assertNotIn("CONGESTED", texte)


if __name__ == "__main__":
    unittest.main()
