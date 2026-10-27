"""Tests de Kafka local (issue LOC-04) : sujets, service Compose et commandes kafka-* de dev.py, sans Docker.

Lancer :  python -m unittest discover -s scripts/dev -v   (Windows : py -3 -m unittest discover -s scripts/dev -v)
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ADR_009 = ROOT / "docs" / "01-architecture" / "adr" / "ADR-009-bus-evenements.md"
SUJETS_DE_L_ISSUE = ["iot.raw", "traffic.indicators", "traffic.recommendations", "alerts.events",
                     "signal.status", "errors.dlq"]
DESCRIPTION = (
    "Topic: iot.raw\tTopicId: AwKkwvFMQMetqOxjOGqi6A\tPartitionCount: 3\tReplicationFactor: 1\t"
    "Configs: min.insync.replicas=1,retention.ms=604800000\n"
    "\tTopic: iot.raw\tPartition: 0\tLeader: 1\tReplicas: 1\tIsr: 1\tElr: \tLastKnownElr: \n"
    "Topic: errors.dlq\tTopicId: kQEQ8fxxTBO9wCfG0wGoCA\tPartitionCount: 3\tReplicationFactor: 1\t"
    "Configs: min.insync.replicas=1\n")


def fake_result(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def description_of(topics, partitions=3):
    lines = []
    for topic in topics:
        configs = ["min.insync.replicas=1", *topic.configs]
        lines.append(f"Topic: {topic.name}\tTopicId: x\tPartitionCount: {partitions}\tReplicationFactor: 1\t"
                     f"Configs: {','.join(configs)}")
    return "\n".join(lines) + "\n"


class SujetsTests(unittest.TestCase):
    def test_les_six_sujets_de_l_issue(self):
        self.assertEqual([t.name for t in dev.KAFKA_TOPICS], SUJETS_DE_L_ISSUE)

    def test_les_sujets_sont_ceux_de_l_adr_009(self):
        texte = ADR_009.read_text(encoding="utf-8")
        tableau = texte.split("### 4.1 Sujets (topics)")[1].split("### 4.2")[0]
        self.assertEqual(re.findall(r"^\| `([a-z.]+)` \|", tableau, re.MULTILINE), SUJETS_DE_L_ISSUE)

    def test_la_cle_est_celle_des_contrats(self):
        # contracts/validate_events.py : subject == data.intersection_id « (clé de partition) »
        self.assertEqual({t.key for t in dev.KAFKA_TOPICS}, {"intersection_id"})

    def test_iot_raw_garde_sept_jours_comme_l_adr_009(self):
        iot = next(t for t in dev.KAFKA_TOPICS if t.name == "iot.raw")
        self.assertEqual(iot.configs, (f"retention.ms={7 * 24 * 3600 * 1000}",))
        self.assertIn("rétention de 7 jours pour `iot.raw`", ADR_009.read_text(encoding="utf-8"))

    def test_les_sujets_sont_ceux_de_la_matrice_des_contrats(self):
        matrice = json.loads((ROOT / "contracts" / "topics.json").read_text(encoding="utf-8"))["topics"]
        self.assertEqual([t.name for t in dev.KAFKA_TOPICS], list(matrice))
        self.assertEqual({t.key for t in dev.KAFKA_TOPICS}, {"intersection_id"})  # la matrice dit : clé = subject
        self.assertEqual({entry["key"] for entry in matrice.values()}, {"subject"})

    def test_les_sujets_des_contrats_sont_crees(self):
        contrats = (ROOT / "contracts" / "README.md").read_text(encoding="utf-8")
        for sujet in re.findall(r"\| `novaria\.[a-z_.0-9]+` \| `([a-z.]+)` \|", contrats):
            self.assertIn(sujet, SUJETS_DE_L_ISSUE)


class ServiceComposeTests(unittest.TestCase):
    def setUp(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.kafka = re.split(r"\n  (?=[#a-z])", compose.split("\n  kafka:\n")[1])[0]  # jusqu'au service ou commentaire suivant

    def test_image_officielle_a_version_fixee(self):
        image = re.search(r"image: (\S+)", self.kafka).group(1)
        self.assertRegex(image, r"^apache/kafka:\d+\.\d+\.\d+$")

    def test_mode_kraft_sans_zookeeper(self):
        self.assertIn("KAFKA_PROCESS_ROLES: broker,controller", self.kafka)
        self.assertNotIn("ZOOKEEPER", self.kafka.upper())

    def test_port_publie_sur_la_boucle_locale_seulement(self):
        ports = re.findall(r'ports: \["([^"]+)"\]', self.kafka)
        self.assertEqual(len(ports), 1)
        self.assertTrue(ports[0].startswith("127.0.0.1:"), ports[0])
        self.assertIn("127.0.0.1:${KAFKA_PORT:-9094}", self.kafka)  # annonce vue du poste = port publié

    def test_sonde_de_sante_et_donnees_persistantes(self):
        self.assertIn("healthcheck:", self.kafka)
        self.assertIn("kafka-broker-api-versions.sh", self.kafka)
        self.assertIn("kafkadata:/var/lib/kafka/data", self.kafka)

    def test_les_sujets_ne_sont_pas_crees_automatiquement(self):
        self.assertIn('KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"', self.kafka)

    def test_kafka_port_est_dans_env_example(self):
        self.assertIn("KAFKA_PORT", dev.parse_env((ROOT / ".env.example").read_text(encoding="utf-8")))


class AnalyseDeSortiesTests(unittest.TestCase):
    def test_description_des_sujets(self):
        found = dev.parse_topic_descriptions(DESCRIPTION)
        self.assertEqual(set(found), {"iot.raw", "errors.dlq"})
        self.assertEqual(found["iot.raw"], (3, 1, {"min.insync.replicas": "1", "retention.ms": "604800000"}))

    def test_decalages(self):
        out = "iot.raw:0:0\niot.raw:1:12\nautre:2:99\n"
        self.assertEqual(dev.parse_offsets(out, "iot.raw"), {0: 0, 1: 12})

    def test_decalages_d_un_sujet_dont_le_nom_contient_un_point(self):
        self.assertEqual(dev.parse_offsets("traffic.indicators:2:7\n", "traffic.indicators"), {2: 7})

    def test_ligne_relue_avec_une_valeur_contenant_le_separateur(self):
        valeur = '{"a":"x|y"}'
        line = f"Partition:1|Offset:4|INT_01|{valeur}"
        self.assertEqual(dev.parse_consumed("bruit\n" + line + "\nProcessed a total of 1 messages\n"),
                         (1, 4, "INT_01", valeur))

    def test_aucune_ligne_relue(self):
        self.assertIsNone(dev.parse_consumed("Processed a total of 0 messages\n"))


class KafkaTopicsTests(unittest.TestCase):
    def run_topics(self, existing, partitions=3):
        calls = []

        def tool(name, *args, **kwargs):
            calls.append((name, args))
            if "--list" in args:
                return fake_result("\n".join(existing) + "\n")
            if "--describe" in args:
                return fake_result(description_of(dev.KAFKA_TOPICS, partitions))
            return fake_result()

        with mock.patch.object(dev, "run_compose_step", return_value=0), \
                mock.patch.object(dev, "kafka_tool", side_effect=tool), mock.patch("builtins.print") as printed:
            code = dev.cmd_kafka_topics(argparse.Namespace())
        return code, calls, "\n".join(str(c.args[0]) for c in printed.call_args_list)

    def test_cree_les_six_sujets_quand_aucun_n_existe(self):
        code, calls, shown = self.run_topics([])
        created = [args[args.index("--topic") + 1] for _, args in calls if "--create" in args]
        self.assertEqual(code, 0)
        self.assertEqual(created, SUJETS_DE_L_ISSUE)
        self.assertIn("6 sujets présents et conformes.", shown)

    def test_ne_recree_pas_un_sujet_existant(self):
        code, calls, shown = self.run_topics(["iot.raw", "errors.dlq"])
        created = [args[args.index("--topic") + 1] for _, args in calls if "--create" in args]
        self.assertEqual(code, 0)
        self.assertEqual(created, ["traffic.indicators", "traffic.recommendations", "alerts.events", "signal.status"])
        self.assertIn("déjà présent", shown)

    def test_la_retention_de_iot_raw_est_passee_a_la_creation(self):
        _, calls, _ = self.run_topics([])
        args = next(a for _, a in calls if "--create" in a and "iot.raw" in a)
        self.assertEqual(args[args.index("--config") + 1], "retention.ms=604800000")

    def test_un_nombre_de_partitions_inattendu_est_signale(self):
        code, _, shown = self.run_topics(SUJETS_DE_L_ISSUE, partitions=1)
        self.assertEqual(code, 1)
        self.assertIn("[KO]", shown)

    def test_un_sujet_absent_apres_creation_est_signale(self):
        def tool(name, *args, **kwargs):
            if "--list" in args:
                return fake_result("")
            if "--describe" in args:
                return fake_result(description_of(dev.KAFKA_TOPICS[:5]))
            return fake_result()

        with mock.patch.object(dev, "run_compose_step", return_value=0), \
                mock.patch.object(dev, "kafka_tool", side_effect=tool), mock.patch("builtins.print"):
            self.assertEqual(dev.cmd_kafka_topics(argparse.Namespace()), 1)

    def test_echec_de_creation_remonte_une_erreur_claire(self):
        def tool(name, *args, **kwargs):
            return fake_result("", 1) if "--create" in args else fake_result("")

        with mock.patch.object(dev, "run_compose_step", return_value=0), \
                mock.patch.object(dev, "kafka_tool", side_effect=tool):
            with self.assertRaises(dev.DevError):
                dev.cmd_kafka_topics(argparse.Namespace())

    def test_kafka_up_attend_la_sonde_de_sante(self):
        with mock.patch.object(dev, "run_compose_step", return_value=0) as step, mock.patch("builtins.print"):
            self.assertEqual(dev.cmd_kafka_up(argparse.Namespace()), 0)
        step.assert_called_once_with("up", "-d", "--wait", "kafka")


@unittest.skipUnless(importlib.util.find_spec("jsonschema") and importlib.util.find_spec("referencing"),
                     "pip install jsonschema referencing")
class AllerRetourTests(unittest.TestCase):
    """Le courtier est simulé par un journal en mémoire : publication, décalages, relecture par partition."""

    def broker(self, corrupt=False, partition=1, publish=True):
        log = []

        def tool(name, *args, input_text=None):
            if name == "kafka-topics.sh":
                return fake_result(description_of(dev.KAFKA_TOPICS))
            if name == "kafka-get-offsets.sh":
                return fake_result(f"iot.raw:0:0\niot.raw:1:{len(log)}\niot.raw:2:0\n" if partition == 1
                                   else f"iot.raw:0:{len(log)}\niot.raw:1:0\n")
            if name == "kafka-console-producer.sh":
                if publish:
                    key, _, value = input_text.rstrip("\n").partition(dev.KAFKA_SEPARATOR)
                    log.append((key, value))
                return fake_result()
            if name == "kafka-console-consumer.sh":
                offset = int(args[args.index("--offset") + 1])
                key, value = log[offset]
                if corrupt:
                    value = value.replace("38.5", "99.9")
                return fake_result(f"Partition:{partition}|Offset:{offset}|{key}|{value}\nProcessed a total of 1 messages\n")
            raise AssertionError(name)

        return tool, log

    def run_roundtrip(self, tool, file=None, topic="iot.raw"):
        args = argparse.Namespace(file=file or dev.EXAMPLE_MEASUREMENT, topic=topic)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(dev, "ENV_FILE", Path(tmp) / ".env"), \
                mock.patch.object(dev, "kafka_tool", side_effect=tool), mock.patch("builtins.print") as printed:
            (Path(tmp) / ".env").write_text("A=1\n", encoding="utf-8")
            code = dev.cmd_kafka_roundtrip(args)
        return code, "\n".join(str(c.args[0]) for c in printed.call_args_list)

    def test_mesure_valide_publiee_relue_et_conforme(self):
        tool, log = self.broker()
        code, shown = self.run_roundtrip(tool)
        self.assertEqual(code, 0)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0][0], "INT_01")  # la clé de partition est le subject
        self.assertIn("conforme au contrat", shown)

    def test_deux_aller_retour_lisent_chacun_leur_propre_message(self):
        tool, log = self.broker()
        self.assertEqual(self.run_roundtrip(tool)[0], 0)
        code, shown = self.run_roundtrip(tool)
        self.assertEqual(code, 0)
        self.assertIn("décalage 1", shown)

    def test_la_partition_est_deduite_des_decalages(self):
        tool, _ = self.broker(partition=0)
        code, shown = self.run_roundtrip(tool)
        self.assertEqual(code, 0)
        self.assertIn("partition 0", shown)

    def test_message_relu_different_du_message_publie(self):
        tool, _ = self.broker(corrupt=True)
        code, shown = self.run_roundtrip(tool)
        self.assertEqual(code, 1)
        self.assertIn("diffère", shown)

    def test_evenement_non_conforme_refuse_par_le_contrat(self):
        event = json.loads(dev.EXAMPLE_MEASUREMENT.read_text(encoding="utf-8"))
        event["data"]["vehicle_count"] = -1
        with tempfile.TemporaryDirectory() as tmp:
            invalid = Path(tmp) / "mesure-invalide.json"
            invalid.write_text(json.dumps(event), encoding="utf-8")
            tool, _ = self.broker()
            code, shown = self.run_roundtrip(tool, file=invalid)
        self.assertEqual(code, 1)
        self.assertIn("[KO]", shown)
        self.assertIn("vehicle_count", shown)

    def test_publication_non_confirmee(self):
        tool, _ = self.broker(publish=False)
        with self.assertRaises(dev.DevError):
            self.run_roundtrip(tool)

    def test_un_evenement_n_est_pas_publie_sur_un_sujet_qui_n_est_pas_le_sien(self):
        tool, log = self.broker()
        with self.assertRaises(dev.DevError) as erreur:
            self.run_roundtrip(tool, file=ROOT / "contracts" / "events" / "examples" / "indicateur-fluide.json")
        self.assertIn("iot.raw", str(erreur.exception))
        self.assertEqual(log, [], "rien ne doit être publié")

    def test_sujet_absent(self):
        def tool(name, *args, **kwargs):
            return fake_result("")

        with self.assertRaises(dev.DevError):
            self.run_roundtrip(tool)


if __name__ == "__main__":
    unittest.main()
