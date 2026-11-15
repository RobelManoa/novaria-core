"""La mesure : découpage des moteurs, échantillonnage de la mémoire, lancement d'un sous-processus, agrégation."""

import os
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from tests import support  # noqa: F401 : chemins d'import

from bigdata import mesure


class Mesure(unittest.TestCase):
    def test_decouper(self):
        self.assertEqual(mesure.decouper("spark:4"), ("spark", 4))
        self.assertEqual(mesure.decouper("python-sequentiel"), ("python-sequentiel", 1))

    @unittest.skipUnless(sys.platform.startswith("linux"), "la mesure de mémoire lit /proc")
    def test_les_descendants_contiennent_le_processus_et_ses_enfants(self):
        import subprocess

        enfant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            self.assertIn(os.getpid(), mesure.descendants(os.getpid()))
            self.assertIn(enfant.pid, mesure.descendants(os.getpid()))
            self.assertGreater(mesure.pss_ko(enfant.pid), 0)
        finally:
            enfant.kill()
            enfant.wait()
        self.assertEqual(mesure.pss_ko(2**22 + 12345), 0, "un processus absent compte pour zéro")

    @unittest.skipUnless(sys.platform.startswith("linux"), "la mesure de mémoire lit /proc")
    def test_lancer_rend_le_json_et_le_pic_de_memoire(self):
        code = "import json,time; x=bytearray(60*1024*1024); x[::4096]=b'1'*len(x[::4096]); time.sleep(0.6); print('bruit'); print(json.dumps({'ok': 1}))"
        resultat, pic = mesure.lancer([sys.executable, "-c", code])
        self.assertEqual(resultat, {"ok": 1})
        self.assertGreater(pic, 50, "le pic voit les 60 Mio alloués par le sous-processus")

    def test_lancer_remonte_l_echec_du_sous_processus(self):
        with self.assertRaises(RuntimeError) as contexte:
            mesure.lancer([sys.executable, "-c", "import sys; sys.stderr.write('boum'); sys.exit(3)"])
        self.assertIn("boum", str(contexte.exception))

    def test_la_commande_porte_tous_les_reglages(self):
        arguments = Namespace(dossier=Path("/d"), sortie=Path("/s"), memoire_spark="2g", temporaire="/t")
        commande = mesure.commande_de("nettoyer", "spark", 4, 7, arguments)
        self.assertEqual(commande[1:5], ["-m", "bigdata", "nettoyer", "--moteur"])
        for morceau in ("spark", "4", "7", "/d", "/s", "2g", "/t"):
            self.assertIn(morceau, commande)

    def test_l_environnement_dit_ou_la_mesure_a_tourne(self):
        environnement = mesure.environnement()
        for cle in ("python", "pyspark", "java", "coeurs_visibles", "cpu_max_cgroup", "memoire_max_cgroup", "noyau"):
            self.assertIn(cle, environnement)

    def test_mesurer_agrege_les_essais_et_compare_les_empreintes(self):
        bilan = {"rows_read": 10, "rows_clean": 8, "rows_rejected": 2, "by_rule": {"TYPE_INVALID": 2}, "flags": {}}
        empreinte = {"propres": {"lignes": 8}, "rejets": {"lignes": 2}}
        sorties = {
            "nettoyer": lambda m: ({"secondes": {"a": 4.0, "b": 2.0}[m], "secondes_demarrage": 0.5, "bilan": bilan}, 100),
            "verifier": lambda m: ({**empreinte, "attendu": bilan}, 50),
        }

        def faux_lancer(commande):
            return sorties[commande[3]](commande[commande.index("--moteur") + 1])

        arguments = Namespace(
            dossier=Path("/d"), sortie=Path("/s"), memoire_spark="1g", temporaire="/t", jours="1", moteurs="a:1,b:2", repetitions=2, rapport=None
        )
        with mock.patch.object(mesure, "lancer", faux_lancer), mock.patch("bigdata.jeu.fichiers_du_jeu", return_value=[Path("x.csv")]), \
                mock.patch("bigdata.jeu.octets_et_lignes", return_value=(1000, 10)):
            rapport = mesure.mesurer(arguments)
        a, b = rapport["mesures"]
        self.assertEqual((a["moteur"], a["mediane_s"], a["lignes_par_seconde"], a["pic_mio"]), ("a", 4.0, 2, 100))
        self.assertEqual((b["moteur"], b["coeurs"], b["mediane_s"], b["lignes_par_seconde"]), ("b", 2, 2.0, 5))
        self.assertTrue(a["bilan_egal_a_la_verite_terrain"])
        self.assertEqual(rapport["parite"], [{"jours": 1, "empreintes_identiques": True, "moteurs": ["a:1", "b:2"]}])
        self.assertEqual(len(a["essais"]), 2)

    def test_une_empreinte_differente_est_signalee(self):
        bilan = {"rows_read": 10, "rows_clean": 8, "rows_rejected": 2, "by_rule": {}, "flags": {}}

        def faux_lancer(commande):
            moteur = commande[commande.index("--moteur") + 1]
            if commande[3] == "nettoyer":
                return {"secondes": 1.0, "secondes_demarrage": 0.0, "bilan": bilan}, 10
            return {"propres": {"lignes": 8 if moteur == "a" else 9}, "rejets": {"lignes": 2}, "attendu": bilan}, 10

        arguments = Namespace(dossier=Path("/d"), sortie=Path("/s"), memoire_spark="1g", temporaire="/t", jours="1", moteurs="a,b", repetitions=1)
        with mock.patch.object(mesure, "lancer", faux_lancer), mock.patch("bigdata.jeu.fichiers_du_jeu", return_value=[Path("x.csv")]), \
                mock.patch("bigdata.jeu.octets_et_lignes", return_value=(1, 10)):
            self.assertFalse(mesure.mesurer(arguments)["parite"][0]["empreintes_identiques"])


if __name__ == "__main__":
    unittest.main()
