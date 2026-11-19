"""`secrets.sh aws` n'active jamais AWS par inadvertance : sans l'accord écrit des deux membres, il refuse et n'appelle pas `gh`.

Un faux `gh` (dans un dossier jetable placé en tête du PATH) enregistre tout appel : le test échoue s'il est appelé.
Lancement : python3 -m unittest discover -s scripts/github -p "test_secrets_aws.py"   (Windows : Git Bash requis ; test ignoré sans bash).
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "secrets.sh"
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "bash introuvable")
class GardeAws(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)
        self.journal = self.dossier / "appels.txt"
        faux = self.dossier / "gh"
        faux.write_text(f'#!/bin/sh\necho "$@" >> "{self.journal}"\n', encoding="utf-8")
        faux.chmod(faux.stat().st_mode | stat.S_IEXEC)
        self.env = {**os.environ, "PATH": f"{self.dossier}{os.pathsep}{os.environ['PATH']}"}
        self.env.pop("NOVARIA_AWS_AUTORISE", None)

    def tearDown(self):
        self._tmp.cleanup()

    def lancer(self, env, entree=""):
        return subprocess.run([BASH, str(SCRIPT), "aws"], input=entree, capture_output=True, text=True, env=env, timeout=30, check=False)

    def test_sans_accord_le_script_refuse_et_n_appelle_pas_gh(self):
        fait = self.lancer(self.env, "eu-west-1\nrole\ncluster\nsb\nsf\nhttps://x\n")
        self.assertEqual(fait.returncode, 1)
        self.assertIn("Refusé", fait.stderr)
        self.assertIn("accord écrit", fait.stderr)
        self.assertFalse(self.journal.exists(), "gh a été appelé alors que l'accord manque")

    def test_une_valeur_approximative_ne_suffit_pas(self):
        for valeur in ("1", "oui", "true", ""):
            fait = self.lancer({**self.env, "NOVARIA_AWS_AUTORISE": valeur})
            self.assertEqual(fait.returncode, 1, valeur)
        self.assertFalse(self.journal.exists())

    def test_avec_l_accord_dit_en_toutes_lettres_les_variables_sont_enregistrees(self):
        fait = self.lancer({**self.env, "NOVARIA_AWS_AUTORISE": "accord-ecrit-des-deux-membres"}, "eu-west-1\nrole\ncluster\nsb\nsf\nhttps://x\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(len(self.journal.read_text(encoding="utf-8").splitlines()), 6)

    def test_les_secrets_non_aws_ne_sont_pas_concernes(self):
        texte = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("for name in SONAR_TOKEN SNYK_TOKEN; do", texte)  # le chemin sans argument ne touche que les deux jetons de qualité
        self.assertNotIn("gh variable", texte.split("for name in")[1].split("done")[0])


if __name__ == "__main__":
    unittest.main()
