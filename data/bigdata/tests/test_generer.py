"""Le générateur : déterminisme, format du portail, et vérité terrain égale au nettoyage de production."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests import support  # noqa: F401 : chemins d'import

from bigdata import generer, jeu, nettoyage_python
from pipelines import nettoyer_paris, paris_comptages

JOUR = date(2026, 10, 1)


class Generateur(unittest.TestCase):
    def test_un_jour_est_deterministe(self):
        premier, attendu = generer.contenu_du_jour(JOUR, capteurs=40)
        second, _ = generer.contenu_du_jour(JOUR, capteurs=40)
        self.assertEqual(premier, second)
        self.assertNotEqual(premier, generer.contenu_du_jour(JOUR, capteurs=40, graine=1)[0])
        self.assertNotEqual(premier, generer.contenu_du_jour(date(2026, 10, 2), capteurs=40)[0])
        self.assertEqual(attendu.lues, attendu.propres + attendu.rejetees)

    def test_le_fichier_a_la_forme_de_l_export_du_portail(self):
        octets, _ = generer.contenu_du_jour(JOUR, capteurs=10)
        self.assertTrue(octets.startswith(b"\xef\xbb\xbf"), "BOM")
        self.assertIn(b"\r\n", octets)
        self.assertEqual(tuple(octets.decode("utf-8-sig").split("\r\n")[0].split(";")), paris_comptages.COLONNES)
        self.assertEqual(generer.COLONNES, paris_comptages.COLONNES)

    def test_le_nom_est_celui_que_le_pipeline_de_production_exige(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = generer.ecrire_le_jour(Path(dossier), JOUR, capteurs=10)
            correspondance = nettoyer_paris.NOM_BRUT.fullmatch(fichier.chemin.name)
            self.assertIsNotNone(correspondance)
            self.assertTrue(paris_comptages.sha256_du_fichier(fichier.chemin).startswith(correspondance.group(3)))
            self.assertEqual(paris_comptages.analyser(fichier.chemin), fichier.attendu.lues)

    def test_un_fichier_existant_n_est_pas_reecrit(self):
        with tempfile.TemporaryDirectory() as dossier:
            premier = generer.ecrire_le_jour(Path(dossier), JOUR, capteurs=10)
            avant = premier.chemin.stat().st_mtime_ns
            second = generer.ecrire_le_jour(Path(dossier), JOUR, capteurs=10)
            self.assertEqual((second.chemin, second.chemin.stat().st_mtime_ns), (premier.chemin, avant))
            self.assertEqual(list(Path(dossier).iterdir()), [premier.chemin])

    def test_la_verite_terrain_est_celle_du_nettoyage_de_production(self):
        """Le générateur sait, sans rien nettoyer, ce que chaque règle doit refuser : le vrai pipeline l'établit."""
        with tempfile.TemporaryDirectory() as dossier:
            fichier = generer.ecrire_le_jour(Path(dossier), JOUR, capteurs=250)
            bilan = nettoyage_python.nettoyer_un(fichier.chemin, generer.MAINTENANT)
        attendu = fichier.attendu.en_dict()
        for cle in ("rows_read", "rows_clean", "rows_rejected", "by_rule", "flags"):
            self.assertEqual(bilan[cle], attendu[cle], cle)

    def test_chaque_regle_voit_passer_des_lignes_et_les_defauts_sont_rares(self):
        _, attendu = generer.contenu_du_jour(JOUR, capteurs=400)
        self.assertEqual(
            set(attendu.par_regle),
            {"MISSING_REQUIRED", "TYPE_INVALID", "OUT_OF_RANGE", "NOT_ON_THE_HOUR", "FUTURE_TIMESTAMP", "STATE_MISMATCH", "DUPLICATE_KEY"},
        )
        self.assertGreater(attendu.drapeaux["MISSING_OCCUPANCY"], 0)
        self.assertGreater(attendu.propres, attendu.lues * 0.7)

    def test_etat_pour_suit_les_seuils_officiels(self):
        self.assertEqual([generer.etat_pour(k) for k in (0, 14.99, 15, 29.9, 30, 49.9, 50, 99)],
                         ["Fluide", "Fluide", "Pré-saturé", "Pré-saturé", "Saturé", "Saturé", "Bloqué", "Bloqué"])

    def test_la_verite_terrain_s_additionne_et_s_indexe(self):
        with tempfile.TemporaryDirectory() as dossier:
            dossier = Path(dossier)
            fichiers = [generer.ecrire_le_jour(dossier, date(2026, 10, jour), capteurs=20) for jour in (1, 2)]
            jeu.enregistrer_attendu(dossier, {f.chemin.name: f.attendu.en_dict() for f in fichiers})
            jeu.enregistrer_attendu(dossier, {})  # l'index existant est conservé
            chemins = jeu.fichiers_du_jeu(dossier)
            total = jeu.attendu_des(dossier, chemins)
            self.assertEqual(total["rows_read"], sum(f.attendu.lues for f in fichiers))
            self.assertEqual(jeu.fichiers_du_jeu(dossier, 1), chemins[:1])
            self.assertEqual(jeu.octets_et_lignes(chemins, dossier), (sum(f.octets for f in fichiers), total["rows_read"]))
            with self.assertRaises(ValueError):
                jeu.fichiers_du_jeu(dossier, 3)

    def test_le_travail_d_un_processus_rend_un_resume(self):
        with tempfile.TemporaryDirectory() as dossier:
            jour, nom, octets, attendu = generer._travail((dossier, JOUR, 10, generer.GRAINE_PAR_DEFAUT))
        self.assertEqual((jour, attendu["rows_read"] > 0, octets > 0), (JOUR.isoformat(), True, True))
        self.assertTrue(nom.endswith(".csv"))


if __name__ == "__main__":
    unittest.main()
