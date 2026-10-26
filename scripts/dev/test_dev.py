"""Tests de scripts/dev/dev.py (sans Docker : les appels sont simulés).

Lancer :  python -m unittest discover -s scripts/dev -v
"""
import argparse
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


class EnvTests(unittest.TestCase):
    def test_generate_env_remplace_chaque_valeur_factice(self):
        text, generated = dev.generate_env(
            "# commentaire\nA_PASSWORD=change-me-local\nB=valeur\nJWT_SECRET=change-me-local-at-least-32-characters\n")
        values = dev.parse_env(text)
        self.assertEqual(generated, 2)
        self.assertEqual(values["B"], "valeur")
        self.assertNotIn(dev.PLACEHOLDER, text)
        self.assertGreaterEqual(len(values["JWT_SECRET"]), 48)
        self.assertGreaterEqual(len(values["A_PASSWORD"]), 24)
        self.assertTrue(text.startswith("# commentaire\n"))

    def test_deux_generations_different(self):
        a, _ = dev.generate_env("X_PASSWORD=change-me-local\n")
        b, _ = dev.generate_env("X_PASSWORD=change-me-local\n")
        self.assertNotEqual(a, b)

    def test_env_example_complet_et_sans_secret_reel(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        for line in text.splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.startswith("#") and ("PASSWORD" in key or "SECRET" in key):
                self.assertTrue(value.startswith(dev.PLACEHOLDER), f"{key} doit contenir une valeur factice")

    def test_toutes_les_variables_du_compose_sont_dans_env_example(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        wanted = set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)[:}?-]", compose))
        known = set(dev.parse_env((ROOT / ".env.example").read_text(encoding="utf-8")))
        self.assertEqual(wanted - known - {"GIT_SHA"}, set(), "variables absentes de .env.example")

    def test_init_env_ne_remplace_pas_et_n_affiche_aucune_valeur(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".env"
            with mock.patch.object(dev, "ENV_FILE", target), mock.patch("builtins.print") as printed:
                self.assertEqual(dev.cmd_init_env(argparse.Namespace(force=False)), 0)
                created = target.read_text(encoding="utf-8")
                self.assertEqual(dev.cmd_init_env(argparse.Namespace(force=False)), 0)
                self.assertEqual(target.read_text(encoding="utf-8"), created)  # inchangé
                self.assertEqual(dev.cmd_init_env(argparse.Namespace(force=True)), 0)
                self.assertNotEqual(target.read_text(encoding="utf-8"), created)  # recréé
            shown = " ".join(str(c.args[0]) for c in printed.call_args_list)
            for value in dev.parse_env(created).values():
                if len(value) >= 24:
                    self.assertNotIn(value, shown)


class CommandTests(unittest.TestCase):
    def run_main(self, argv):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("A=1\n", encoding="utf-8")
            with mock.patch.object(dev, "ENV_FILE", env), \
                    mock.patch("subprocess.run", side_effect=fake_run), \
                    mock.patch("shutil.which", return_value="/usr/bin/docker"):
                code = dev.main(argv)
        return code, calls

    def test_db_up_attend_les_bases_puis_migre(self):
        code, calls = self.run_main(["db-up"])
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["docker", "compose", "up", "-d", "--wait", "postgres", "mongo"])
        self.assertEqual(calls[1], ["docker", "compose", "run", "--rm", "db-migrate"])

    def test_backup_lance_les_deux_bases_avec_le_profil_ops(self):
        code, calls = self.run_main(["backup"])
        self.assertEqual(code, 0)
        self.assertEqual([c[-2] for c in calls], ["backup-postgres", "backup-mongo"])
        self.assertTrue(all("--profile" in c and "ops" in c for c in calls))

    def test_restore_check_d_un_fichier_ne_verifie_que_sa_base(self):
        _, calls = self.run_main(["restore-check", "novaria_x.dump"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-3:], ["backup-postgres", "restore-check", "novaria_x.dump"])
        _, calls = self.run_main(["restore-check", "novaria_x.archive.gz"])
        self.assertEqual(calls[0][-3:], ["backup-mongo", "restore-check", "novaria_x.archive.gz"])

    def test_restore_check_par_defaut_verifie_les_deux_bases(self):
        _, calls = self.run_main(["restore-check"])
        self.assertEqual([c[-3] for c in calls], ["backup-postgres", "backup-mongo"])

    def test_restore_demande_confirmation_et_ne_touche_a_rien_sinon(self):
        with mock.patch("builtins.input", return_value="oui"):
            code, calls = self.run_main(["restore"])
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])

    def test_restore_arrete_l_application_puis_restaure_les_deux_bases(self):
        code, calls = self.run_main(["restore", "--yes", "--mongo", "novaria_x.archive.gz"])
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["docker", "compose", "stop", "backend", "frontend"])
        self.assertEqual(calls[1][-3:], ["backup-postgres", "restore", "latest"])
        self.assertEqual(calls[2][-3:], ["backup-mongo", "restore", "novaria_x.archive.gz"])
        self.assertTrue(all("CONFIRM_RESTORE=yes" in c for c in calls[1:]))

    def test_db_reset_demande_confirmation(self):
        with mock.patch("builtins.input", return_value="non"):
            code, calls = self.run_main(["db-reset"])
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])

    def test_db_reset_confirme_supprime_les_volumes(self):
        code, calls = self.run_main(["db-reset", "--yes"])
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ["docker", "compose", "down", "-v"])

    def test_sans_env_message_clair(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(dev, "ENV_FILE", Path(tmp) / "absent.env"), \
                mock.patch("sys.stderr"):
            self.assertEqual(dev.main(["db-up"]), 2)

    def test_sans_docker_message_clair(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(dev.DevError):
                dev.require_docker()

    def test_db_check_compte_les_ecarts(self):
        # Tout réussit : les contrôles « interdit » deviennent des échecs.
        results = []

        def fake_run(cmd, **kwargs):
            results.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("A=1\n", encoding="utf-8")
            with mock.patch.object(dev, "ENV_FILE", env), mock.patch("subprocess.run", side_effect=fake_run), \
                    mock.patch("shutil.which", return_value="/usr/bin/docker"), mock.patch("builtins.print"):
                code = dev.cmd_db_check(argparse.Namespace())
        refused = sum(1 for *_, expected in dev.build_checks() if not expected)
        self.assertEqual(code, 1)
        self.assertEqual(len(results), len(dev.build_checks()))
        self.assertGreater(refused, 0)

    def test_les_controles_n_exposent_aucun_mot_de_passe(self):
        for _, _, command, _ in dev.build_checks():
            self.assertNotRegex(command, r"change-me|password=\w", "pas de mot de passe en clair")
            if "-p " in command:
                self.assertRegex(command, r'-p "\$[A-Z_]+"')


if __name__ == "__main__":
    unittest.main()
