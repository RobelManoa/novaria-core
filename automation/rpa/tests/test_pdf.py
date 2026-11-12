import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tests import donnees  # noqa: F401

from rapport import pdf

MAINTENANT = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)


def document(lignes=1, **kw):
    doc = pdf.Document(kw.get("titre", "Titre éprouvé"), MAINTENANT)
    doc.titre_principal("Rapport")
    for n in range(lignes):
        doc.paragraphe(f"Ligne {n} : débit (véh/min) \\ 5 % — « essai »")
    return doc.octets()


class EcritureDePdf(unittest.TestCase):
    def test_le_fichier_est_un_pdf_en_ascii_pur(self):
        contenu = document()
        self.assertTrue(contenu.startswith(b"%PDF-1.4\n"))
        self.assertTrue(contenu.endswith(b"%%EOF\n"))
        contenu.decode("ascii")  # aucune exception : les accents passent en octal

    def test_la_table_xref_pointe_chaque_objet_a_son_decalage_exact(self):
        contenu = document(120)  # plusieurs pages
        debut = int(re.search(rb"startxref\n(\d+)\n%%EOF", contenu).group(1))
        self.assertTrue(contenu[debut:].startswith(b"xref\n"))
        entrees = re.findall(rb"(\d{10}) 00000 n \n", contenu[debut:])
        self.assertGreater(len(entrees), 5)
        for numero, position in enumerate(entrees, start=1):
            self.assertTrue(contenu[int(position):].startswith(f"{numero} 0 obj\n".encode()), numero)
        taille = int(re.search(rb"/Size (\d+)", contenu).group(1))
        self.assertEqual(taille, len(entrees) + 1)

    def test_les_flux_declarent_leur_longueur_exacte(self):
        contenu = document(30)
        for longueur, flux in re.findall(rb"/Length (\d+) >>\nstream\n(.*?)\nendstream", contenu, re.S):
            self.assertEqual(int(longueur), len(flux))

    def test_un_long_texte_ajoute_des_pages_et_le_compte_est_juste(self):
        court, long = document(3), document(200)
        self.assertEqual(re.search(rb"/Count (\d+)", court).group(1), b"1")
        pages = int(re.search(rb"/Count (\d+)", long).group(1))
        self.assertGreater(pages, 2)
        self.assertEqual(len(re.findall(rb"/Type /Page /Parent", long)), pages)

    def test_aucune_ligne_ne_sort_de_la_page(self):
        contenu = document(200)
        for y in re.findall(rb"1 0 0 1 \d+ (\d+) Tm", contenu):
            self.assertGreaterEqual(int(y), pdf.MARGE)
            self.assertLessEqual(int(y), pdf.HAUTEUR - pdf.MARGE)

    def test_les_caracteres_speciaux_sont_echappes(self):
        self.assertEqual(pdf.chaine("a(b)c\\d"), "(a\\(b\\)c\\\\d)")
        self.assertEqual(pdf.chaine("é"), "(\\351)")
        self.assertEqual(pdf.chaine("—"), "(\\227)")
        self.assertEqual(pdf.chaine("日"), "(?)")  # hors cp1252 : remplacé, jamais d'erreur

    def test_le_titre_du_document_garde_ses_accents(self):
        self.assertIn(pdf.chaine_unicode("Titre éprouvé").encode(), document())

    def test_la_date_de_creation_est_celle_donnee(self):
        self.assertIn(b"D:20261026060000Z", document())

    def test_la_meme_entree_donne_les_memes_octets(self):
        self.assertEqual(document(10), document(10))

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext absent")
    def test_un_lecteur_de_pdf_retrouve_le_texte_et_les_accents(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "essai.pdf"
            chemin.write_bytes(document(2))
            texte = subprocess.run(["pdftotext", "-layout", str(chemin), "-"], capture_output=True, text=True, check=True).stdout
        self.assertIn("Rapport", texte)
        self.assertIn("débit (véh/min)", texte)
        self.assertIn("« essai »", texte)


if __name__ == "__main__":
    unittest.main()
