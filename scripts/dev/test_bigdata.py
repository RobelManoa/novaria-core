"""Les commandes Docker du prototype Big Data (DAT-08) : le dépôt est monté en lecture seule, rien n'écrit dans le projet.

Bibliothèque standard seulement, sans Docker. Lancement : python3 -m unittest discover -s scripts/dev -p "test_bigdata.py"
(Windows : py -3 ...).
"""

import unittest
from pathlib import Path

import bigdata_docker as bd

RACINE = Path(__file__).resolve().parents[2]


class CommandesDocker(unittest.TestCase):
    def test_la_construction_part_du_dossier_du_prototype(self):
        commande = bd.commande_de_construction(RACINE)
        self.assertEqual(commande[:4], ["docker", "build", "-t", bd.IMAGE])
        self.assertTrue(commande[-1].endswith("bigdata"))
        self.assertTrue(Path(commande[commande.index("-f") + 1]).is_file(), "le Dockerfile existe")

    def test_le_depot_est_monte_en_lecture_seule_et_les_donnees_dans_un_volume(self):
        commande = bd.commande_de_lancement(RACINE, ["mesurer", "--jours", "7"])
        montages = [commande[i + 1] for i, mot in enumerate(commande) if mot == "-v"]
        self.assertEqual(montages, [f"{RACINE}:/repo:ro", f"{bd.VOLUME}:/data"])
        self.assertEqual(commande[-3:], ["mesurer", "--jours", "7"])
        self.assertIn("--rm", commande)

    def test_les_ressources_sont_limitees_et_reglables(self):
        defaut = bd.commande_de_lancement(RACINE, ["nettoyer"])
        self.assertEqual((defaut[defaut.index("--cpus") + 1], defaut[defaut.index("--memory") + 1]), ("4", "6g"))
        regle = bd.commande_de_lancement(RACINE, ["nettoyer"], cpus="8", memoire="12g")
        self.assertEqual((regle[regle.index("--cpus") + 1], regle[regle.index("--memory") + 1]), ("8", "12g"))

    def test_les_tests_tournent_dans_l_image_depuis_le_dossier_du_prototype(self):
        commande = bd.commande_de_test(RACINE)
        self.assertEqual(commande[commande.index("--entrypoint") + 1], "python")
        self.assertEqual(commande[commande.index("--workdir") + 1], "/repo/data/bigdata")
        self.assertEqual(commande[-7:], ["-m", "unittest", "discover", "-s", "tests", "-t", "."])
        self.assertNotIn("nettoyer", commande)

    def test_le_dockerfile_installe_pyspark_avec_ses_empreintes(self):
        dockerfile = (RACINE / "data" / "bigdata" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("--require-hashes", dockerfile)
        exigences = (RACINE / "data" / "bigdata" / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(exigences, r"pyspark==\d+\.\d+\.\d+ \\\n\s+--hash=sha256:[0-9a-f]{64}")
        self.assertIn("pyspark==", (RACINE / "data" / "bigdata" / "requirements.in").read_text(encoding="utf-8"))

    def test_le_dockerfile_ne_tourne_pas_en_root_et_ne_copie_pas_le_code(self):
        dockerfile = (RACINE / "data" / "bigdata" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER novaria", dockerfile)
        self.assertNotRegex(dockerfile, r"(?m)^COPY (?!requirements\.txt)")


if __name__ == "__main__":
    unittest.main()
