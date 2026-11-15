import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from tests.donnees import FausseApi

from rapport import __main__ as principal
from rapport import api, chaine, depot

ENV = {"NOVARIA_RPA_USER": "robot", "NOVARIA_RPA_PASSWORD": "secret-de-test-12"}
MAINTENANT = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)


class Chaine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name) / "rapports"

    def produire(self, api_fausse=None, **kw):
        return chaine.produire("http://127.0.0.1:8000", self.dossier, debut="2026-10-19", maintenant=MAINTENANT,
                               envoyer=api_fausse or FausseApi(), environnement=ENV, **kw)

    def test_un_rapport_est_produit_de_bout_en_bout_sans_intervention(self):
        resultat = self.produire()
        pdf = resultat.chemin_pdf.read_bytes()
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertEqual(resultat.metadonnees["size_bytes"], len(pdf))
        self.assertIn("ROAD_002", pdf.decode("ascii"))

    def test_le_rapport_dit_que_les_donnees_sont_simulees(self):
        import shutil
        import subprocess

        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext absent")
        resultat = self.produire()
        texte = subprocess.run(["pdftotext", "-layout", str(resultat.chemin_pdf), "-"], capture_output=True, text=True, check=True).stdout
        self.assertIn("simulées", texte)
        self.assertIn("aucun trafic réel", texte)
        self.assertIn("ROAD_002", texte)

    def test_une_periode_sans_donnee_donne_quand_meme_un_rapport_qui_le_dit(self):
        resultat = self.produire(FausseApi([]))
        self.assertTrue(resultat.chemin_pdf.is_file())

    def test_relancer_remplace_le_rapport(self):
        self.assertFalse(self.produire().remplace)
        self.assertTrue(self.produire().remplace)
        self.assertEqual(len(list(self.dossier.glob("*.json"))), 1)

    def test_une_notification_est_ecrite(self):
        self.produire()
        ligne = json.loads((self.dossier / depot.NOM_NOTIFICATIONS).read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(ligne["niveau"], "INFO")
        self.assertIn("2026-S43", ligne["message"])

    def test_sans_identifiants_rien_n_est_appele_ni_depose(self):
        fausse = FausseApi()
        with self.assertRaises(chaine.IdentifiantsAbsents):
            chaine.produire("http://x", self.dossier, envoyer=fausse, environnement={})
        self.assertEqual(fausse.appels, [])
        self.assertFalse(self.dossier.exists())

    def test_les_identifiants_ne_viennent_que_de_l_environnement(self):
        self.assertEqual(chaine.identifiants(ENV), ("robot", "secret-de-test-12"))
        with self.assertRaises(chaine.IdentifiantsAbsents):
            chaine.identifiants({"NOVARIA_RPA_USER": "robot"})

    def test_aucun_secret_dans_le_pdf_ni_les_metadonnees_ni_les_notifications(self):
        self.produire()
        for chemin in self.dossier.iterdir():
            contenu = chemin.read_bytes()
            self.assertNotIn(b"secret-de-test-12", contenu, chemin.name)
            self.assertNotIn(b"jeton-opaque", contenu, chemin.name)


class LigneDeCommande(unittest.TestCase):
    def lancer(self, *arguments, api_fausse=None, env=ENV):
        sortie, erreur = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(sortie), redirect_stderr(erreur), \
                mock.patch.dict("os.environ", env, clear=True), mock.patch.object(api, "_envoyer", api_fausse or FausseApi()):
            dossier = Path(tmp) / "rapports"
            code = principal.main(["--dossier", str(dossier), *arguments])
            notifications = (dossier / depot.NOM_NOTIFICATIONS) if (dossier / depot.NOM_NOTIFICATIONS).exists() else None
            lignes = [json.loads(x) for x in notifications.read_text(encoding="utf-8").splitlines()] if notifications else []
        return code, sortie.getvalue(), erreur.getvalue(), lignes

    def test_code_zero_et_description_json_du_rapport(self):
        code, sortie, _, lignes = self.lancer("--debut", "2026-10-19")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(sortie)["content_type"], "application/pdf")
        self.assertEqual(lignes[0]["niveau"], "INFO")

    def test_une_api_qui_refuse_donne_le_code_un_et_une_notification_d_erreur(self):
        code, _, erreur, lignes = self.lancer("--debut", "2026-10-19", api_fausse=FausseApi(mot_de_passe="autre"))
        self.assertEqual(code, 1)
        self.assertIn("401", erreur)
        self.assertEqual(lignes[-1]["niveau"], "ERREUR")
        self.assertNotIn("secret-de-test-12", erreur + json.dumps(lignes))

    def test_une_saisie_invalide_donne_le_code_deux_sans_appel(self):
        fausse = FausseApi()
        code, _, erreur, lignes = self.lancer("--debut", "pas-une-date", api_fausse=fausse)
        self.assertEqual((code, fausse.appels, lignes), (2, [], []))
        self.assertIn("AAAA-MM-JJ", erreur)

    def test_sans_identifiants_le_code_est_deux(self):
        code, _, erreur, _ = self.lancer("--debut", "2026-10-19", env={})
        self.assertEqual(code, 2)
        self.assertIn("NOVARIA_RPA_USER", erreur)
        self.assertNotIn("secret", erreur)


if __name__ == "__main__":
    unittest.main()
