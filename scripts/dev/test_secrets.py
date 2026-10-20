"""Contrôle de l'inventaire des secrets (issue GES-16) : bibliothèque standard seulement.

Vérifie que docs/04-devsecops/secrets.md cite chaque secret du projet, donne un propriétaire à chacun
et ne contient aucune valeur de forme jeton.
Lancement : python3 -m unittest discover -s scripts/dev   (Windows : py -3 -m unittest discover -s scripts/dev)
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = ROOT / "docs" / "04-devsecops" / "secrets.md"
PLACEHOLDER = "change-me-local"


def secrets_de_la_ci() -> set[str]:
    noms = set()
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        noms |= set(re.findall(r"secrets\.([A-Z][A-Z0-9_]*)", workflow.read_text(encoding="utf-8")))
    return noms - {"GITHUB_TOKEN"}


def secrets_locaux() -> set[str]:
    noms = set()
    for ligne in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        cle, separateur, valeur = ligne.partition("=")
        if separateur and not ligne.lstrip().startswith("#") and valeur.startswith(PLACEHOLDER):
            noms.add(cle)
    return noms


def lignes_d_inventaire(texte: str) -> list[dict[str, str]]:
    """Lignes des tableaux dont la première cellule est S<n> ou L<n>, indexées par l'en-tête de leur tableau."""
    lignes, entete = [], []
    for ligne in texte.splitlines():
        if not ligne.startswith("|"):
            entete = []
            continue
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if set("".join(cellules)) <= set("-: "):
            continue
        if not entete:
            entete = cellules
        elif re.fullmatch(r"[SL]\d+", cellules[0]) and len(cellules) == len(entete):
            lignes.append(dict(zip(entete, cellules)))
    return lignes


class InventaireDesSecrets(unittest.TestCase):
    def setUp(self):
        self.texte = DOCUMENT.read_text(encoding="utf-8")
        self.lignes = lignes_d_inventaire(self.texte)

    def test_chaque_secret_de_la_ci_est_inventorie(self):
        self.assertTrue(secrets_de_la_ci(), "aucun secret de CI trouvé")
        for nom in secrets_de_la_ci():
            with self.subTest(secret=nom):
                self.assertIn(f"`{nom}`", self.texte)

    def test_chaque_secret_local_est_inventorie(self):
        self.assertTrue(secrets_locaux(), "aucun secret local trouvé")
        for nom in secrets_locaux():
            with self.subTest(secret=nom):
                self.assertIn(f"`{nom}`", self.texte)

    def test_chaque_ligne_a_un_proprietaire(self):
        self.assertGreaterEqual(len(self.lignes), 5 + 2 + 12)
        for ligne in self.lignes:
            with self.subTest(secret=ligne["N°"]):
                self.assertTrue(ligne.get("Propriétaire"), "propriétaire absent")

    def test_chaque_secret_externe_a_une_expiration_et_un_renouvellement(self):
        externes = [ligne for ligne in self.lignes if "Expiration" in ligne]
        self.assertGreaterEqual(len(externes), 7)
        for ligne in externes:
            with self.subTest(secret=ligne["N°"]):
                self.assertTrue(ligne["Expiration"])
                self.assertTrue(ligne["Renouvellement"])

    def test_le_jeton_snyk_expire_mi_janvier_2027(self):
        for ligne in self.lignes:
            if ligne["N°"] in ("S1", "S2"):
                self.assertIn("janvier 2027", ligne["Expiration"])

    def test_le_document_ne_contient_aucune_valeur_de_forme_jeton(self):
        motifs = {
            "UUID": r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
            "préfixe de jeton": r"\b(ghp_|gho_|github_pat_|glpat-|sqp_|squ_|sqa_|snyk_uat\.|AKIA)[A-Za-z0-9_]{8,}",
            "clé privée": r"-----BEGIN [A-Z ]*PRIVATE KEY",
            "longue chaîne aléatoire": r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}\b",
        }
        for nom, motif in motifs.items():
            with self.subTest(motif=nom):
                self.assertIsNone(re.search(motif, self.texte), f"valeur de forme « {nom} » dans le document")


if __name__ == "__main__":
    unittest.main()
