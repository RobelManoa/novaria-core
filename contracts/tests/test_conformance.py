"""Conformité par service et par sujet (MS-03). Lancer :
    python3 -m unittest discover -s contracts/tests -v        (Windows : py -3 -m unittest ...)
Dépendances : pip install jsonschema referencing

Critère d'acceptation : chaque service publie et consomme uniquement des messages conformes au contrat ; le test échoue sinon.
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import conformance as cf  # noqa: E402
import validate_events as ve  # noqa: E402
from cases import INVALID_CASES, load, mutate  # noqa: E402

REPO = ROOT.parent
ADR_009 = REPO / "docs" / "01-architecture" / "adr" / "ADR-009-bus-evenements.md"
SERVICE_DE = {"Collecte": ["collecte"], "Traitement": ["traitement"], "Alerte": ["alerte"],
              "Réponse extérieure": ["reponse"], "Tous": ["collecte", "traitement", "alerte", "reponse"]}


class MatriceDesSujets(unittest.TestCase):
    def setUp(self):
        self.registry = cf.load_registry()

    def test_six_sujets_un_contrat_par_sujet(self):
        topics = self.registry["topics"]
        self.assertEqual(list(topics), ["iot.raw", "traffic.indicators", "traffic.recommendations", "alerts.events",
                                        "signal.status", "errors.dlq"])
        self.assertEqual(len({t["type"] for t in topics.values()}), 6, "un type d'événement par sujet")
        self.assertEqual(len({t["schema"] for t in topics.values()}), 6, "un schéma par sujet")

    def test_le_type_et_le_schema_de_chaque_sujet_sont_connus_du_validateur(self):
        for topic, entry in self.registry["topics"].items():
            with self.subTest(topic=topic):
                self.assertEqual(ve.SCHEMA_BY_TYPE[entry["type"]], entry["schema"])
                self.assertTrue((ROOT / "events" / entry["schema"]).is_file())

    def test_le_validateur_ne_connait_aucun_type_hors_matrice(self):
        self.assertEqual(set(ve.SCHEMA_BY_TYPE), {t["type"] for t in self.registry["topics"].values()})

    def test_les_producteurs_sont_ceux_de_l_adr_009(self):
        texte = ADR_009.read_text(encoding="utf-8")
        tableau = texte.split("### 4.1 Sujets (topics)")[1].split("### 4.2")[0]
        for topic, producteur in re.findall(r"^\| `([a-z.]+)` \| ([^|]+?) \|", tableau, re.MULTILINE):
            with self.subTest(topic=topic):
                nom = producteur.strip()
                self.assertEqual(self.registry["topics"][topic]["producers"], SERVICE_DE[nom])

    def test_les_services_cites_existent(self):
        connus = set(self.registry["services"])
        for topic, entry in self.registry["topics"].items():
            self.assertLessEqual(set(entry["producers"]) | set(entry["consumers"]), connus, topic)

    def test_chaque_sujet_a_un_producteur(self):
        for topic, entry in self.registry["topics"].items():
            self.assertTrue(entry["producers"], topic)

    def test_la_cle_de_partition_est_le_sujet_de_l_enveloppe(self):
        for entry in self.registry["topics"].values():
            self.assertEqual(entry["key"], "subject")

    def test_chaque_service_publie_ou_consomme_quelque_chose(self):
        for name, rights in cf.services().items():
            self.assertTrue(rights["publishes"] or rights["consumes"], name)


class ExemplesParService(unittest.TestCase):
    def test_chaque_service_publie_et_consomme_des_exemples_conformes(self):
        examples = cf.examples_by_topic()
        checked = 0
        for service, rights in cf.services().items():
            for topic in rights["publishes"]:
                own = [(n, e) for n, e in examples[topic]
                       if cf.load_registry()["topics"][topic]["source"] == "origin" or e["source"] == service]
                self.assertTrue(own, f"{service} publie {topic} sans exemple")
                for name, event in own:
                    with self.subTest(service=service, publie=topic, exemple=name):
                        self.assertEqual(cf.publication_errors(service, topic, event), [])
                        cf.assert_publication(service, topic, event)
                        checked += 1
            for topic in rights["consumes"]:
                self.assertTrue(examples[topic], f"{service} consomme {topic} sans exemple")
                for name, event in examples[topic]:
                    with self.subTest(service=service, consomme=topic, exemple=name):
                        self.assertEqual(cf.consumption_errors(service, topic, event), [])
                        cf.assert_consumption(service, topic, event)
                        checked += 1
        self.assertGreaterEqual(checked, 33)  # 19 publications et 14 consommations d'exemples

    def test_la_ligne_de_commande_controle_tout_et_reussit(self):
        with unittest_stdout():
            self.assertEqual(cf.main([]), 0)


class MessagesHorsContrat(unittest.TestCase):
    """Le test doit échouer quand un service sort du contrat : chaque dérive est refusée, des deux côtés."""

    def test_un_message_invalide_est_refuse_a_la_publication_et_a_la_consommation(self):
        topic_of = {e["type"]: t for t, e in cf.load_registry()["topics"].items()}
        refused = 0
        for description, exemple, change, fragment in INVALID_CASES:
            event = mutate(exemple, change)
            topic = topic_of[event["type"]] if event.get("type") in topic_of else topic_of[load(exemple)["type"]]
            entry = cf.load_registry()["topics"][topic]
            producer, consumer = entry["producers"][0], (entry["consumers"] or [None])[0]
            with self.subTest(cas=description):
                with self.assertRaises(cf.ContractViolation):
                    cf.assert_publication(producer, topic, event)
                if consumer:
                    with self.assertRaises(cf.ContractViolation):
                        cf.assert_consumption(consumer, topic, event)
                refused += 1
        self.assertEqual(refused, len(INVALID_CASES))

    def test_un_service_ne_publie_pas_sur_un_sujet_qui_n_est_pas_le_sien(self):
        mesure = load("mesure-valide.json")
        errors = cf.publication_errors("reponse", "iot.raw", mesure)
        self.assertTrue(any("n'a pas le droit de publier sur iot.raw" in e for e in errors), errors)
        with self.assertRaises(cf.ContractViolation):
            cf.assert_publication("traitement", "iot.raw", mesure)

    def test_un_service_ne_consomme_pas_un_sujet_qui_n_est_pas_le_sien(self):
        errors = cf.consumption_errors("collecte", "iot.raw", load("mesure-valide.json"))
        self.assertTrue(any("n'a pas le droit de consommer iot.raw" in e for e in errors), errors)

    def test_un_message_conforme_mais_sur_le_mauvais_sujet_est_refuse(self):
        errors = cf.publication_errors("traitement", "traffic.indicators", load("recommandation-plan.json"))
        self.assertTrue(any("refusé sur traffic.indicators" in e for e in errors), errors)
        errors = cf.consumption_errors("traitement", "iot.raw", load("indicateur-fluide.json"))
        self.assertTrue(any("refusé sur iot.raw" in e for e in errors), errors)

    def test_un_service_ne_signe_pas_un_rejet_au_nom_d_un_autre(self):
        rejet = load("rejet-contrat.json")  # source : collecte
        self.assertEqual(cf.publication_errors("collecte", "errors.dlq", rejet), [])
        errors = cf.publication_errors("alerte", "errors.dlq", rejet)
        self.assertTrue(any("signé par le service qui le publie" in e for e in errors), errors)

    def test_sujet_service_et_message_inconnus(self):
        self.assertTrue(cf.message_errors("autre.sujet", {}))
        self.assertTrue(cf.publication_errors("inconnu", "iot.raw", load("mesure-valide.json")))
        self.assertTrue(cf.publication_errors("collecte", "iot.raw", "pas un objet"))
        self.assertTrue(cf.message_errors("iot.raw", [1, 2]))

    def test_aucun_exemple_ne_passe_par_hasard_sur_un_autre_sujet(self):
        for topic, entry in cf.load_registry()["topics"].items():
            for other, other_entry in cf.load_registry()["topics"].items():
                if other == topic:
                    continue
                for name, event in cf.examples_by_topic()[topic]:
                    self.assertTrue(cf.message_errors(other, event), f"{name} accepté sur {other}")


class unittest_stdout:
    """Masque la sortie d'une commande pendant un test."""

    def __enter__(self):
        import contextlib
        import io
        self._ctx = contextlib.redirect_stdout(io.StringIO())
        self._ctx.__enter__()

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)


class Versionnement(unittest.TestCase):
    """Règles de versionnement : schema_version = majeure.mineure ; la majeure est celle du type (`...v1`)."""

    def schemas(self):
        for topic, entry in cf.load_registry()["topics"].items():
            yield topic, json.loads((ROOT / "events" / entry["schema"]).read_text(encoding="utf-8")), entry

    def test_schema_version_est_majeure_point_mineure_et_suit_le_type(self):
        for topic, schema, entry in self.schemas():
            with self.subTest(topic=topic):
                properties = schema["allOf"][1]["properties"]
                version = properties["schema_version"]["const"]
                self.assertRegex(version, r"^[0-9]+\.[0-9]+$")
                majeure_du_type = re.search(r"\.v([0-9]+)$", properties["type"]["const"]).group(1)
                self.assertEqual(version.split(".")[0], majeure_du_type)

    def test_chaque_exemple_porte_la_version_de_son_schema(self):
        for topic, exemples in cf.examples_by_topic().items():
            schema = json.loads((ROOT / "events" / cf.load_registry()["topics"][topic]["schema"]).read_text(encoding="utf-8"))
            version = schema["allOf"][1]["properties"]["schema_version"]["const"]
            for name, event in exemples:
                with self.subTest(exemple=name):
                    self.assertEqual(event["schema_version"], version)

    def test_l_identifiant_du_schema_est_son_nom_de_fichier(self):
        for path in (ROOT / "events").glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(schema["$id"].endswith("/contracts/events/" + path.name), path.name)

    def test_chaque_schema_de_sujet_est_ferme_aux_champs_inconnus(self):
        for topic, schema, entry in self.schemas():
            with self.subTest(topic=topic):
                self.assertIs(schema["$defs"]["data"]["additionalProperties"], False)

    def test_le_message_le_plus_ancien_reste_valide(self):
        # filet de compatibilité : les exemples ne sont jamais réécrits pour s'adapter à un schéma plus strict
        for path in sorted((ROOT / "events" / "examples").glob("*.json")):
            with self.subTest(exemple=path.name):
                self.assertEqual(ve.validate_event(json.loads(path.read_text(encoding="utf-8"))), [])


if __name__ == "__main__":
    unittest.main()
