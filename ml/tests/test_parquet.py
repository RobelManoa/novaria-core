"""Écrivain Parquet en bibliothèque standard : structure, relecture exacte, déterminisme, refus des entrées fausses."""

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tests import support  # noqa: F401

from jeu_entrainement import parquet as pq

COLONNES = [
    pq.Colonne("run", "string", False), pq.Colonne("n", "int32", False), pq.Colonne("grand", "int64"),
    pq.Colonne("x", "double"), pq.Colonne("ok", "bool", False), pq.Colonne("t", "timestamp", False), pq.Colonne("s", "string"),
]


def lignes(n=130):
    return [
        (f"run-é{i % 3}", i, None if i % 4 == 0 else i * 10**12, None if i % 3 == 0 else i / 7, i % 2 == 0,
         datetime(2026, 10, 20, 6, i % 60, tzinfo=UTC), None if i % 5 == 0 else "日本語 « cité »")
        for i in range(n)
    ]


class Parquet(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name)

    def test_le_fichier_porte_la_signature_et_une_longueur_de_pied_de_page_juste(self):
        chemin = self.dossier / "a.parquet"
        pq.ecrire(chemin, COLONNES, lignes())
        octets = chemin.read_bytes()
        self.assertEqual((octets[:4], octets[-4:]), (b"PAR1", b"PAR1"))
        taille = int.from_bytes(octets[-8:-4], "little")
        meta, fin = pq.read_struct(octets, len(octets) - 8 - taille)
        self.assertEqual(fin, len(octets) - 8)
        self.assertEqual(meta[3], 130)  # nombre de lignes

    def test_la_relecture_rend_exactement_les_memes_colonnes_et_lignes(self):
        chemin = self.dossier / "a.parquet"
        pq.ecrire(chemin, COLONNES, lignes(), taille_groupe=50)
        colonnes, relues = pq.lire(chemin)
        self.assertEqual(colonnes, COLONNES)
        self.assertEqual(relues, lignes())

    def test_plusieurs_groupes_de_lignes_et_un_seul_donnent_les_memes_lignes(self):
        for taille in (1, 7, 50, 130, 1000):
            with self.subTest(taille=taille):
                chemin = self.dossier / f"g{taille}.parquet"
                pq.ecrire(chemin, COLONNES, lignes(), taille_groupe=taille)
                self.assertEqual(pq.lire(chemin)[1], lignes())

    def test_deux_ecritures_donnent_les_memes_octets(self):
        a, b = self.dossier / "a.parquet", self.dossier / "b.parquet"
        pq.ecrire(a, COLONNES, lignes())
        pq.ecrire(b, COLONNES, lignes())
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_le_fichier_ne_contient_ni_date_d_ecriture_ni_chemin(self):
        chemin = self.dossier / "a.parquet"
        pq.ecrire(chemin, COLONNES, lignes())
        self.assertNotIn(str(self.dossier).encode(), chemin.read_bytes())

    def test_un_fichier_sans_ligne_se_relit(self):
        chemin = self.dossier / "vide.parquet"
        pq.ecrire(chemin, COLONNES, [])
        self.assertEqual(pq.lire(chemin), (COLONNES, []))

    def test_les_valeurs_extremes_et_les_chaines_vides_passent(self):
        colonnes = [pq.Colonne("a", "int64", False), pq.Colonne("b", "string", False), pq.Colonne("c", "double", False)]
        donnees = [(-(2**63), "", -0.0), (2**63 - 1, "x" * 5000, 1e308), (0, "é", 5e-324)]
        chemin = self.dossier / "e.parquet"
        pq.ecrire(chemin, colonnes, donnees)
        self.assertEqual(pq.lire(chemin)[1], donnees)

    def test_les_entrees_fausses_sont_refusees(self):
        chemin = self.dossier / "x.parquet"
        cas = {
            "absent dans une colonne obligatoire": ([pq.Colonne("a", "int32", False)], [(None,)]),
            "booléen donné pour un entier": ([pq.Colonne("a", "int32", False)], [(True,)]),
            "texte donné pour un double": ([pq.Colonne("a", "double")], [("1.5",)]),
            "entier trop grand pour 32 bits": ([pq.Colonne("a", "int32")], [(2**31,)]),
            "horodatage sans fuseau": ([pq.Colonne("a", "timestamp")], [(datetime(2026, 1, 1),)]),
            "ligne trop courte": ([pq.Colonne("a", "int32"), pq.Colonne("b", "int32")], [(1,)]),
            "NaN": ([pq.Colonne("a", "double")], [(float("nan"),)]),
        }
        for nom, (colonnes, donnees) in cas.items():
            with self.subTest(nom), self.assertRaises(pq.ParquetError):
                pq.ecrire(chemin, colonnes, donnees)

    def test_des_noms_de_colonnes_en_double_ou_aucune_colonne_sont_refuses(self):
        with self.assertRaises(pq.ParquetError):
            pq.ecrire(self.dossier / "x", [pq.Colonne("a", "int32"), pq.Colonne("a", "int32")], [])
        with self.assertRaises(pq.ParquetError):
            pq.ecrire(self.dossier / "x", [], [])

    def test_un_fichier_qui_n_est_pas_du_parquet_est_refuse_a_la_lecture(self):
        chemin = self.dossier / "x.parquet"
        chemin.write_bytes(b"pas du parquet du tout")
        with self.assertRaises(pq.ParquetError):
            pq.lire(chemin)

    def test_un_lecteur_independant_relit_les_memes_valeurs(self):
        try:
            import pyarrow.parquet as lecteur
        except ImportError:
            self.skipTest("pyarrow n'est pas installé (outil d'essai, pas une dépendance du jeu)")
        chemin = self.dossier / "a.parquet"
        pq.ecrire(chemin, COLONNES, lignes(), taille_groupe=50)
        table = lecteur.read_table(chemin)
        relues = list(zip(*[table.column(i).to_pylist() for i in range(table.num_columns)], strict=True))
        self.assertEqual(relues, lignes())
        self.assertEqual(lecteur.ParquetFile(chemin).num_row_groups, 3)
        self.assertEqual(str(table.schema.field("t").type), "timestamp[us, tz=UTC]")
        self.assertTrue(table.schema.field("run").nullable is False)


if __name__ == "__main__":
    unittest.main()
