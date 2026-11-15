"""Intégrité du jeu (cadrage ML, S1) : un fichier altéré, manquant ou ajouté, un manifeste incohérent sont refusés."""

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from tests import support  # noqa: F401 : chemins d'import

from jeu_entrainement import integrite
from jeu_entrainement.__main__ import main
from jeu_entrainement.construire import SORTIE_PAR_DEFAUT, empreinte_du_jeu
from stockage import sha256


def fabriquer(dossier: Path) -> dict:
    """Un petit jeu : deux fichiers et un manifeste cohérent."""
    fichiers = {}
    for nom, octets in (("train.parquet", b"PAR1 entrainement PAR1"), ("test.parquet", b"PAR1 test PAR1")):
        (dossier / nom).write_bytes(octets)
        fichiers[nom] = {"octets": len(octets), "sha256": sha256(octets)}
    manifeste = {"dataset_id": "jeu-d-essai", "fichiers": fichiers, "empreinte_du_jeu": empreinte_du_jeu(fichiers)}
    (dossier / "manifest.json").write_text(json.dumps(manifeste), encoding="utf-8")
    return manifeste


class Integrite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name)
        self.manifeste = fabriquer(self.dossier)

    def test_un_jeu_intact_n_a_aucun_ecart(self):
        self.assertEqual(integrite.verifier(self.dossier), [])
        self.assertEqual(integrite.verifier(self.dossier, self.manifeste["empreinte_du_jeu"]), [])

    def test_un_octet_change_est_refuse(self):
        (self.dossier / "train.parquet").write_bytes(b"PAR1 entrainement PAR2")  # même taille, autre contenu
        ecarts = integrite.verifier(self.dossier)
        self.assertEqual(len(ecarts), 1)
        self.assertIn("train.parquet : SHA-256 différent", ecarts[0])

    def test_une_taille_differente_est_refusee(self):
        (self.dossier / "test.parquet").write_bytes(b"PAR1 test PAR1 et une ligne de plus")
        self.assertIn("octets", integrite.verifier(self.dossier)[0])

    def test_un_fichier_manquant_est_refuse(self):
        (self.dossier / "test.parquet").unlink()
        self.assertEqual(integrite.verifier(self.dossier), ["test.parquet : fichier manquant"])

    def test_un_fichier_parquet_ajoute_est_refuse(self):
        (self.dossier / "supplementaire.parquet").write_bytes(b"PAR1 PAR1")
        self.assertEqual(integrite.verifier(self.dossier), ["supplementaire.parquet : fichier Parquet absent du manifeste"])

    def test_un_manifeste_dont_l_empreinte_ne_suit_pas_ses_fichiers_est_refuse(self):
        self.manifeste["fichiers"]["test.parquet"]["sha256"] = "0" * 64
        (self.dossier / "manifest.json").write_text(json.dumps(self.manifeste), encoding="utf-8")
        ecarts = integrite.verifier(self.dossier)
        self.assertTrue(any("test.parquet : SHA-256 différent" in e for e in ecarts))
        self.assertTrue(any("l'empreinte du jeu ne correspond pas" in e for e in ecarts))

    def test_un_manifeste_reecrit_avec_les_fichiers_est_vu_par_l_empreinte_attendue(self):
        ancienne = self.manifeste["empreinte_du_jeu"]
        (self.dossier / "train.parquet").write_bytes(b"PAR1 donnees empoisonnees PAR1")
        fabriquer_apres = {"octets": (self.dossier / "train.parquet").stat().st_size, "sha256": sha256((self.dossier / "train.parquet").read_bytes())}
        self.manifeste["fichiers"]["train.parquet"] = fabriquer_apres
        self.manifeste["empreinte_du_jeu"] = empreinte_du_jeu(self.manifeste["fichiers"])
        (self.dossier / "manifest.json").write_text(json.dumps(self.manifeste), encoding="utf-8")
        self.assertEqual(integrite.verifier(self.dossier), [], "cohérent en lui-même : seul l'empreinte citée ailleurs le trahit")
        self.assertIn("différente de l'empreinte attendue", integrite.verifier(self.dossier, ancienne)[0])

    def test_un_nom_de_fichier_hors_regle_est_un_ecart_pas_une_exception(self):
        self.manifeste["fichiers"]["../evade.parquet"] = {"octets": 1, "sha256": "0" * 64}
        self.manifeste["empreinte_du_jeu"] = empreinte_du_jeu(self.manifeste["fichiers"])
        (self.dossier / "manifest.json").write_text(json.dumps(self.manifeste), encoding="utf-8")
        ecarts = integrite.verifier(self.dossier)
        self.assertEqual(len(ecarts), 1)
        self.assertIn("../evade.parquet : illisible", ecarts[0])

    def test_manifeste_absent_ou_illisible(self):
        (self.dossier / "manifest.json").write_text("pas du json", encoding="utf-8")
        self.assertIn("illisible", integrite.verifier(self.dossier)[0])
        (self.dossier / "manifest.json").unlink()
        self.assertIn("absent", integrite.verifier(self.dossier)[0])

    def test_la_ligne_de_commande_donne_le_code_de_sortie(self):
        sortie, erreur = StringIO(), StringIO()
        with redirect_stdout(sortie), redirect_stderr(erreur):
            self.assertEqual(main(["--verifier", "--sortie", str(self.dossier)]), 0)
            (self.dossier / "test.parquet").unlink()
            self.assertEqual(main(["--verifier", "--sortie", str(self.dossier)]), 1)
        self.assertIn("Jeu intact", sortie.getvalue())
        self.assertIn("NON conforme", sortie.getvalue())
        self.assertIn("fichier manquant", erreur.getvalue())


@unittest.skipUnless((SORTIE_PAR_DEFAUT / "train.parquet").is_file(), "jeu v1 absent : python3 ml/src/construire_jeu.py")
class SurLeJeuV1(unittest.TestCase):
    def test_le_jeu_v1_du_poste_est_intact(self):
        self.assertEqual(integrite.verifier(), [])


if __name__ == "__main__":
    unittest.main()
