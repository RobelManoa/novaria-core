"""Contrôle des registres de gestion (issue GES-07) : bibliothèque standard seulement.

Lancement : python3 -m unittest discover -s scripts/dev   (Windows : py -3 -m unittest discover -s scripts/dev)
"""
import re
import unittest
from pathlib import Path

GESTION = Path(__file__).resolve().parents[2] / "docs" / "07-gestion"
RESPONSABLES = {"Daddy", "Manoa", "Les deux"}
COLONNES_RISQUES = ["ID", "Risque", "Cause", "Effet", "Responsable", "Action", "Signal de suivi", "Statut"]


def lire(nom: str) -> str:
    return (GESTION / nom).read_text(encoding="utf-8")


def lignes_de_tableau(texte: str, motif_id: str) -> list[list[str]]:
    """Cellules de chaque ligne de tableau Markdown dont la première cellule correspond à `motif_id`."""
    lignes = []
    for ligne in texte.splitlines():
        if not ligne.startswith("|"):
            continue
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if re.fullmatch(motif_id, cellules[0]):
            lignes.append(cellules)
    return lignes


class RegistreDesRisques(unittest.TestCase):
    def setUp(self):
        self.texte = lire("registre-risques.md")
        self.risques = lignes_de_tableau(self.texte, r"R\d+")

    def test_les_colonnes_demandees_existent(self):
        entete = next(l for l in self.texte.splitlines() if l.startswith("| ID "))
        self.assertEqual([c.strip() for c in entete.strip().strip("|").split("|")], COLONNES_RISQUES)

    def test_les_cinq_premiers_risques_sont_presents(self):
        identifiants = [r[0] for r in self.risques]
        for attendu in ("R1", "R2", "R3", "R4", "R5"):
            self.assertIn(attendu, identifiants)

    def test_chaque_risque_a_toutes_ses_cellules_un_responsable_valide_et_une_action(self):
        for risque in self.risques:
            with self.subTest(risque=risque[0]):
                self.assertEqual(len(risque), len(COLONNES_RISQUES))
                self.assertTrue(all(risque), "cellule vide")
                self.assertIn(risque[4], RESPONSABLES)

    def test_les_identifiants_sont_uniques(self):
        identifiants = [r[0] for r in self.risques]
        self.assertEqual(len(identifiants), len(set(identifiants)))


class JournalDesChangements(unittest.TestCase):
    def test_chaque_demande_du_registre_des_demandes_est_au_journal(self):
        demandes = {c[0] for c in lignes_de_tableau(lire("registre-des-demandes.md"), r"C-\d+")}
        journal = set(re.findall(r"\bC-\d+\b", lire("journal-changements.md")))
        self.assertTrue(demandes, "aucune demande trouvée dans le registre des demandes")
        self.assertEqual(sorted(demandes - journal), [], "demandes absentes du journal")

    def test_le_journal_est_dans_l_ordre_des_dates(self):
        dates = re.findall(r"^\| (\d{2})/(\d{2})/(\d{4}) \|", lire("journal-changements.md"), re.M)
        cles = [(a, m, j) for j, m, a in dates]
        self.assertEqual(cles, sorted(cles))


if __name__ == "__main__":
    unittest.main()
