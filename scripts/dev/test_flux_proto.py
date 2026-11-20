"""Le prototype de flux temps réel (DAT-09) : branchement dans dev.py, Makefile, Compose et SQL.

La logique du prototype se teste dans `data/streaming/tests/` (sans Docker). Ici, seulement ce qui relie le prototype au reste du dépôt :
la commande `dev.py flux-proto`, les cibles du Makefile, et les invariants de `data/streaming/` que le reste du dépôt suppose
(connecteurs épinglés, aucun secret, prototype hors de `docker-compose.yml`).
"""

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import dev

RACINE = Path(__file__).resolve().parents[2]
PROTO = RACINE / "data" / "streaming"


class CommandeDev(unittest.TestCase):
    def test_la_commande_transmet_ses_arguments_au_prototype_sans_le_separateur(self):
        sys.path.insert(0, str(PROTO))
        try:
            from streaming import cli
        finally:
            sys.path.remove(str(PROTO))
        with mock.patch.object(dev, "require_docker"), mock.patch.object(cli, "main", return_value=0) as main:
            code = dev.main(["flux-proto", "--", "demo", "--duree", "5m"])
        self.assertEqual(code, 0)
        main.assert_called_once_with(["demo", "--duree", "5m"])

    def test_sans_commande_le_message_dit_quoi_faire(self):
        with self.assertRaises(dev.DevError) as contexte:
            dev.cmd_flux_proto(dev.build_parser().parse_args(["flux-proto"]))
        self.assertIn("flux-proto demo", str(contexte.exception))

    def test_le_chemin_du_prototype_n_est_pas_laisse_dans_sys_path(self):
        avant = list(sys.path)
        with mock.patch.object(dev, "require_docker"):
            try:
                dev.cmd_flux_proto(dev.build_parser().parse_args(["flux-proto", "--", "build", "--aide-inexistante"]))
            except SystemExit:
                pass  # l'analyseur du prototype refuse l'option inconnue : seul le chemin nous intéresse
        self.assertEqual(sys.path, avant)

    def test_les_cibles_make_sont_declarees_phony_et_documentees(self):
        makefile = (RACINE / "Makefile").read_text(encoding="utf-8")
        phony = re.search(r"(?m)^\.PHONY:(.*)$", makefile).group(1).split()
        for cible in ("flux-proto", "test-flux-proto"):
            self.assertIn(cible, phony)
            self.assertRegex(makefile, rf"(?m)^{cible}:\s+##")


class InvariantsDuPrototype(unittest.TestCase):
    def test_le_prototype_n_est_pas_dans_le_docker_compose_de_la_racine(self):
        racine = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("flink", racine.lower())

    def test_les_connecteurs_sont_epingles_par_empreinte(self):
        dockerfile = (PROTO / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^FROM flink:\d+\.\d+\.\d+-java\d+@sha256:[0-9a-f]{64}$")
        empreintes = re.findall(r"--checksum=sha256:([0-9a-f]{64})", dockerfile)
        self.assertEqual(len(empreintes), 2, "un connecteur Kafka et un connecteur MongoDB, chacun avec son empreinte")
        self.assertEqual(len(re.findall(r"https://repo1\.maven\.org/maven2/", dockerfile)), 2)

    def test_aucun_secret_ni_adresse_avec_mot_de_passe_dans_le_prototype(self):
        for fichier in [p for p in PROTO.rglob("*") if p.is_file() and p.suffix in {".sql", ".yml", ".py", ".md", ""} and "__pycache__" not in p.parts and "tests" not in p.parts]:  # les tests contiennent de faux mots de passe, voulus
            texte = fichier.read_text(encoding="utf-8", errors="replace")
            self.assertIsNone(re.search(r"mongodb://[^\s{}'\"]+:[^\s{}'\"@]+@", texte.replace("u:p@", "")), f"adresse avec mot de passe dans {fichier.name}")
            self.assertNotRegex(texte, r"change-me", fichier.name)

    def test_le_compose_du_prototype_borne_la_memoire_de_flink_et_de_kafka(self):
        compose = (PROTO / "compose.yml").read_text(encoding="utf-8")
        self.assertRegex(compose, r"jobmanager\.memory\.process\.size: \d+m")
        self.assertRegex(compose, r"taskmanager\.memory\.process\.size: \d+m")
        self.assertIn("KAFKA_HEAP_OPTS", compose)
        self.assertIn("wiredTigerCacheSizeGB", compose)


if __name__ == "__main__":
    unittest.main()
