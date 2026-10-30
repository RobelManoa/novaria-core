"""Les faux positifs de gitleaks sont rares, exacts et justifiés ; la commande de la CI reste stricte.

`.gitleaksignore` écarte une détection précise de l'historique, sans désactiver de règle. Ce test
vérifie qu'il ne devient pas une porte ouverte : chaque ligne est une empreinte exacte, présente et
datée dans docs/04-devsecops/exceptions.md (section 11), et la commande de la CI n'a pas été affaiblie.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_gitleaks.py"   (Windows : py -3 ...)
"""
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
EMPREINTE = re.compile(r"[0-9a-f]{40}:[\w./-]+:[\w-]+:[0-9]+")


def lignes_d_empreintes() -> list[str]:
    texte = (RACINE / ".gitleaksignore").read_text(encoding="utf-8")
    return [ligne.strip() for ligne in texte.splitlines() if ligne.strip() and not ligne.lstrip().startswith("#")]


def section_onze() -> str:
    texte = (RACINE / "docs" / "04-devsecops" / "exceptions.md").read_text(encoding="utf-8")
    debut = texte.index("## 11. Faux positifs de gitleaks")
    return texte[debut:]


class Gitleaks(unittest.TestCase):
    def test_chaque_ligne_est_une_empreinte_exacte_sans_joker(self):
        empreintes = lignes_d_empreintes()
        self.assertTrue(empreintes)
        for empreinte in empreintes:
            with self.subTest(empreinte=empreinte):
                self.assertRegex(empreinte, EMPREINTE)
                self.assertFalse(set(empreinte) & set("*?[]{}"), "pas de motif : une empreinte exacte")

    def test_chaque_empreinte_est_justifiee_et_datee_dans_la_politique(self):
        section = section_onze()
        for empreinte in lignes_d_empreintes():
            with self.subTest(empreinte=empreinte):
                ligne = next((ligne for ligne in section.splitlines() if empreinte in ligne), "")
                self.assertTrue(ligne, "empreinte absente du tableau de la section 11")
                self.assertRegex(ligne, r"20[0-9]{2}-[0-9]{2}-[0-9]{2}")
                self.assertIn("rien à révoquer", ligne)

    def test_aucune_empreinte_n_est_listee_sans_etre_ignoree(self):
        section = section_onze()
        documentees = set(re.findall(r"`([0-9a-f]{40}:[^`]+)`", section))
        self.assertEqual(documentees, set(lignes_d_empreintes()))

    def test_aucune_regle_n_est_desactivee_ni_aucun_chemin_exclu(self):
        self.assertFalse((RACINE / ".gitleaks.toml").exists(), "pas de configuration qui allège les règles")
        self.assertFalse((RACINE / "gitleaks.toml").exists())

    def test_la_commande_de_la_ci_n_est_pas_affaiblie(self):
        ci = (RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        bloc = ci[ci.index("  gitleaks:") : ci.index("  snyk:")]
        self.assertIn("fetch-depth: 0", bloc, "tout l'historique est lu")
        self.assertIn("gitleaks:latest detect --source /repo --redact --verbose", bloc)
        for interdit in ("--exit-code", "|| true", "continue-on-error", "--no-git", "--baseline", "--config"):
            self.assertNotIn(interdit, bloc)

    def test_le_secret_d_essai_du_code_ne_ressemble_plus_a_un_litteral_de_cle(self):
        fakes = (RACINE / "services" / "traitement" / "tests" / "fakes.py").read_text(encoding="utf-8")
        self.assertNotRegex(fakes, r"""(?mi)^\w*(secret|key|token)\w*\s*=\s*["'][\w.=-]{10,}["']""")


if __name__ == "__main__":
    unittest.main()
