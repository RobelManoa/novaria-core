"""Les tableaux du compte rendu, à partir d'un petit rapport de mesure inventé (les chiffres sont ceux du test, pas ceux du rapport)."""

import json
import tempfile
import unittest
from pathlib import Path

from tests import support  # noqa: F401 : chemins d'import

from bigdata import rapport


def mesure(moteur, coeurs, jours, secondes, demarrage=0.0, pic=100, verite=True):
    return {
        "moteur": moteur, "coeurs": coeurs, "jours": jours, "fichiers": jours, "lignes": 1000 * jours, "octets": 2_000_000 * jours,
        "essais": [], "mediane_s": secondes, "mediane_demarrage_s": demarrage, "pic_mio": pic,
        "lignes_par_seconde": round(1000 * jours / secondes), "bilan_egal_a_la_verite_terrain": verite,
    }


RAPPORT = {
    "environnement": {"python": "3.12", "pyspark": "4.1.4", "java": "openjdk", "coeurs_visibles": 12, "cpu_max_cgroup": "400000 100000",
                      "memoire_max_cgroup": "6442450944", "noyau": "7"},
    "mesures": [
        mesure("python-sequentiel", 1, 1, 2.0, pic=50), mesure("python-parallele", 4, 1, 1.0, pic=300), mesure("spark", 4, 1, 12.0, 4.0, 900),
        mesure("python-sequentiel", 1, 10, 20.0, pic=50), mesure("python-parallele", 4, 10, 6.0, pic=300), mesure("spark", 4, 10, 5.0, 4.0, 1200),
    ],
    "parite": [{"jours": 1, "empreintes_identiques": True, "moteurs": ["a", "b"]}, {"jours": 10, "empreintes_identiques": False, "moteurs": ["a", "b"]}],
}


class Rapport(unittest.TestCase):
    def test_durees_par_taille_et_par_moteur(self):
        tableau = rapport.tableau_durees(RAPPORT)
        self.assertIn("| 1 | 1 000 | 2 Mo | 2,0 s (500 l/s) | 1,0 s (1 000 l/s) | 12,0 s (83 l/s) |", tableau)
        self.assertIn("python-parallele (4 cœurs)", tableau.splitlines()[0])

    def test_memoire_et_demarrage(self):
        self.assertIn("| 10 | 50 Mio | 300 Mio | 1 200 Mio |", rapport.tableau_memoire(RAPPORT))
        self.assertIn("| 1 | spark (4 cœurs) | 4,0 s | 12,0 s | 33 % |", rapport.tableau_demarrage(RAPPORT))

    def test_rapports_et_point_de_croisement(self):
        self.assertEqual(rapport.rapports_de_duree(RAPPORT, "python-sequentiel", "spark (4 cœurs)"), [(1, 2 / 12), (10, 4.0)])
        self.assertEqual(rapport.point_de_croisement(RAPPORT, "spark (4 cœurs)", "python-sequentiel"), 10)
        self.assertEqual(rapport.point_de_croisement(RAPPORT, "spark (4 cœurs)", "python-parallele (4 cœurs)"), 10)
        self.assertEqual(rapport.point_de_croisement(RAPPORT, "python-sequentiel", "spark (4 cœurs)"), 1)  # l'ETL séquentiel bat Spark dès 1 jour
        petit = {**RAPPORT, "mesures": RAPPORT["mesures"][:3]}
        self.assertIsNone(rapport.point_de_croisement(petit, "spark (4 cœurs)", "python-sequentiel"))  # Spark ne le bat jamais
        tableau = rapport.tableau_rapports(RAPPORT)
        self.assertIn("| 10 | 4,00 | 1,20 |", tableau)

    def test_une_taille_absente_donne_un_tiret(self):
        partiel = {**RAPPORT, "mesures": RAPPORT["mesures"][:3] + [mesure("spark", 4, 10, 5.0, 4.0, 1200)]}
        self.assertIn("| 10 | — | — |", rapport.tableau_rapports(partiel))
        self.assertIn("—", rapport.tableau_durees(partiel))

    def test_la_parite_signale_un_ecart(self):
        tableau = rapport.tableau_parite({**RAPPORT, "mesures": RAPPORT["mesures"][:5] + [mesure("spark", 4, 10, 5.0, verite=False)]})
        self.assertIn("| 1 | a, b | oui | oui |", tableau)
        self.assertIn("| 10 | a, b | **NON** | **NON** |", tableau)

    def test_rendre_un_fichier(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "mesure.json"
            chemin.write_text(json.dumps(RAPPORT), encoding="utf-8")
            texte = rapport.rendre(chemin)
        self.assertIn("PySpark 4.1.4", texte)
        self.assertIn("Parité", texte)

    def test_sans_pyspark_le_tableau_des_rapports_est_vide(self):
        sans = {**RAPPORT, "mesures": [m for m in RAPPORT["mesures"] if m["moteur"] != "spark"]}
        self.assertEqual(len(rapport.tableau_rapports(sans).splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
