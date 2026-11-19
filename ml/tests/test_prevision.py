"""Prévision de vitesse (IA-10) : variables sans fuite du futur, références, métriques, source, et la chaîne sur une série fabriquée.

Aucun test ne lit METR-LA ni ne se connecte au réseau : le téléchargement est essayé avec une réponse fausse, et la chaîne
complète tourne sur une série à profil journalier fabriquée. Les tests qui entraînent un modèle ont besoin de scikit-learn
et de numpy (`ml/.venv`, `python3 scripts/dev/dev.py ml-env`) ; ils sont ignorés sans eux.
"""

import hashlib
import io
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tests import support  # noqa: F401  (chemins d'import)

from prevision import source

try:
    import numpy as np
    import sklearn  # noqa: F401

    from prevision import evaluation, rapport, references, variables
    from prevision.donnees import MS_PAR_PAS, Serie, serie_depuis_un_run

    OUTILS = True
except ImportError:
    OUTILS = False


try:
    import h5py
except ImportError:
    h5py = None


class Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Source(unittest.TestCase):
    def test_l_empreinte_et_la_taille_sont_celles_de_la_fiche(self):
        fiche = (support.RACINE / "data" / "datasets" / "metr-la" / "PROVENANCE.md").read_text(encoding="utf-8")
        self.assertIn(source.SHA256, fiche)
        self.assertIn(f"{source.TAILLE_OCTETS:,}".replace(",", " "), fiche)
        self.assertIn(source.IDENTIFIANT_DRIVE, fiche)

    def test_un_fichier_absent_ou_modifie_est_refuse_sans_etre_lu(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "metr-la.h5"
            with self.assertRaisesRegex(source.FichierRefuse, "absent"):
                source.verifier(chemin)
            chemin.write_bytes(b"x" * 10)
            with self.assertRaisesRegex(source.FichierRefuse, "octets"):
                source.verifier(chemin)

    def test_la_taille_juste_avec_une_empreinte_fausse_est_refusee(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "metr-la.h5"
            chemin.write_bytes(b"\0" * source.TAILLE_OCTETS)
            with self.assertRaisesRegex(source.FichierRefuse, "SHA-256"):
                source.verifier(chemin)

    def test_un_telechargement_refuse_ne_laisse_aucun_fichier(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(source.FichierRefuse):
                source.telecharger(Path(d), ouvrir=lambda url, timeout: Reponse(b"<html>page d'erreur</html>"))
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_un_telechargement_conforme_est_renomme_puis_pas_retelecharge(self):
        contenu = b"jeu de test"
        appels = []

        def ouvrir(url, timeout):
            appels.append(url)
            return Reponse(contenu)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(source, "TAILLE_OCTETS", len(contenu)), \
                mock.patch.object(source, "SHA256", hashlib.sha256(contenu).hexdigest()):
            chemin = source.telecharger(Path(d), ouvrir=ouvrir)
            self.assertEqual(chemin.read_bytes(), contenu)
            source.telecharger(Path(d), ouvrir=ouvrir)
            self.assertEqual(len(appels), 1)
            self.assertEqual([p.name for p in Path(d).iterdir()], ["metr-la.h5"])


def serie_journaliere(jours=14, capteurs=4, bruit=0.0, graine=1):
    """Vitesse = profil journalier (creux de pointe) propre à chaque capteur, plus du bruit ; 5 % de mesures manquantes."""
    rng = np.random.default_rng(graine)
    pas = jours * 288
    t = np.arange(pas)
    fraction = (t % 288) / 288
    profil = 60 - 25 * np.exp(-((fraction - 0.33) ** 2) / 0.004) - 20 * np.exp(-((fraction - 0.72) ** 2) / 0.006)
    vitesses = np.stack([profil - 3 * k for k in range(capteurs)], axis=1) + rng.normal(0, bruit, (pas, capteurs))
    vitesses[rng.random((pas, capteurs)) < 0.05] = np.nan
    return Serie("fabriquee", (t.astype(np.int64) * MS_PAR_PAS) + 1_330_560_000_000, tuple(f"c{k}" for k in range(capteurs)), vitesses)


@unittest.skipUnless(OUTILS, "numpy et scikit-learn absents : python3 scripts/dev/dev.py ml-env")
class Variables(unittest.TestCase):
    def setUp(self):
        self.serie = serie_journaliere(jours=4, bruit=1.0)
        self.brut = self.serie.vitesses
        self.rempli = variables.remplir(self.brut, 50.0)

    def test_remplir_reprend_la_derniere_mesure_connue_et_jamais_la_suivante(self):
        brut = np.array([[np.nan], [10.0], [np.nan], [np.nan], [20.0]])
        self.assertEqual(variables.remplir(brut, 7.0)[:, 0].tolist(), [7.0, 10.0, 10.0, 10.0, 20.0])

    def test_les_variables_ne_dependent_que_du_passe(self):
        """Changer le futur d'un pas `t` ne change pas la ligne de `t`."""
        t = np.array([600])
        avant = variables.matrice(self.brut, self.rempli, self.serie.instants_ms, t)
        modifie = self.brut.copy()
        modifie[601:] = 1.0
        apres = variables.matrice(modifie, variables.remplir(modifie, 50.0), self.serie.instants_ms, t)
        np.testing.assert_array_equal(avant, apres)

    def test_la_matrice_a_une_ligne_par_capteur_et_les_bons_noms(self):
        x = variables.matrice(self.brut, self.rempli, self.serie.instants_ms, np.array([300, 301]))
        self.assertEqual(x.shape, (2 * 4, len(variables.NOMS)))
        np.testing.assert_allclose(x[:4, 0], self.rempli[300])
        np.testing.assert_allclose(x[:4, variables.NOMS.index("lag2")], self.rempli[298])

    def test_aucune_variable_n_identifie_le_capteur(self):
        self.assertFalse({"capteur", "id", "moyenne_capteur"} & set(variables.NOMS))

    def test_heure_et_semaine(self):
        jeudi_minuit = np.array([0])  # 1er janvier 1970, un jeudi
        sin, cos, _, _, weekend = variables.variables_temporelles(jeudi_minuit)
        self.assertEqual((float(sin[0]), float(cos[0]), float(weekend[0])), (0.0, 1.0, 0.0))
        samedi = np.array([2 * variables.JOUR_MS])
        self.assertEqual(float(variables.variables_temporelles(samedi)[4][0]), 1.0)

    def test_moyenne_glissante_ignore_les_manquants(self):
        brut = np.array([[10.0], [np.nan], [20.0], [30.0]])
        m = variables.moyenne_glissante(brut, variables.remplir(brut, 0.0), np.array([3]), 4)
        self.assertEqual(float(m[0, 0]), 20.0)

    def test_les_reponses_sont_la_vitesse_a_t_plus_h(self):
        y = variables.reponses(self.brut, np.array([10, 11]), 3)
        np.testing.assert_array_equal(y, self.brut[[13, 14]].reshape(-1))


@unittest.skipUnless(OUTILS, "numpy et scikit-learn absents")
class References(unittest.TestCase):
    def test_persistance_moyenne_et_naif_saisonnier(self):
        pas = 600
        brut = np.arange(pas, dtype=float)[:, None] % 100 + 1
        rempli = variables.remplir(brut, 1.0)
        t = np.array([400, 401])
        r = references.calculer(brut, rempli, t, 3)
        self.assertEqual(r["persistance"].tolist(), [brut[400, 0], brut[401, 0]])
        self.assertAlmostEqual(r["moyenne_glissante"][0], brut[389:401, 0].mean())
        self.assertEqual(r["naif_saisonnier"].tolist(), [brut[400 + 3 - 288, 0], brut[401 + 3 - 288, 0]])

    def test_le_naif_saisonnier_est_non_applicable_sans_une_journee_de_passe(self):
        brut = np.ones((100, 2))
        self.assertIsNone(references.calculer(brut, brut, np.array([50]), 3)["naif_saisonnier"])


@unittest.skipUnless(OUTILS, "numpy et scikit-learn absents")
class Evaluation(unittest.TestCase):
    def test_mae_et_rmse_masquees(self):
        reel = np.array([10.0, np.nan, 20.0, 30.0])
        prevision = np.array([11.0, 99.0, 18.0, 30.0])
        m = evaluation.metriques(prevision, reel)
        self.assertEqual(m["n"], 3)
        self.assertAlmostEqual(m["mae"], 1.0)
        self.assertAlmostEqual(m["rmse"], float(np.sqrt((1 + 4 + 0) / 3)))

    def test_l_ecart_par_jour_donne_un_intervalle_qui_contient_l_ecart_et_son_signe(self):
        rng = np.random.default_rng(0)
        jours = np.repeat(np.arange(20), 50)
        reel = rng.normal(50, 5, len(jours))
        bon = reel + rng.normal(0, 1, len(jours))
        mauvais = reel + rng.normal(0, 3, len(jours))
        a, n = evaluation.somme_par_jour(bon, reel, jours)
        b, _ = evaluation.somme_par_jour(mauvais, reel, jours)
        e = evaluation.ecart_de_mae(a, b, n)
        self.assertLess(e["ecart_mae"], 0)
        self.assertLess(e["haut"], 0)
        self.assertLessEqual(e["bas"], e["ecart_mae"])
        self.assertEqual(e["jours"], 20)
        self.assertEqual(e, evaluation.ecart_de_mae(a, b, n))  # graine fixe

    def test_deux_methodes_identiques_ont_un_ecart_nul(self):
        jours = np.repeat(np.arange(5), 10)
        reel = np.arange(50, dtype=float)
        a, n = evaluation.somme_par_jour(reel + 1, reel, jours)
        e = evaluation.ecart_de_mae(a, a, n)
        self.assertEqual((e["ecart_mae"], e["bas"], e["haut"]), (0.0, 0.0, 0.0))


@unittest.skipUnless(OUTILS, "numpy et scikit-learn absents")
class Chaine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from prevision import modeles

        cls.fabriques = dict(modeles.FABRIQUES)
        modeles.FABRIQUES = {"ridge": (modeles.ridge, ({"alpha": 1.0},)),
                             "hist_gradient_boosting": (modeles.hgb, ({"max_leaf_nodes": 15, "max_iter": 40, "learning_rate": 0.2},))}
        cls.modeles = modeles
        cls.serie = serie_journaliere(jours=40, capteurs=5, bruit=1.5)
        cls.sortie = []
        cls.resultats, cls.choisis = rapport.evaluer_metr_la(cls.serie, progres=cls.sortie.append, pas_apprentissage=2)

    @classmethod
    def tearDownClass(cls):
        cls.modeles.FABRIQUES = cls.fabriques

    def test_les_parties_se_suivent_dans_le_temps_avec_un_delai_de_garde(self):
        p = self.resultats["donnees"]["parties"]
        self.assertLess(p["train"]["fin"], p["validation"]["debut"])
        self.assertLess(p["validation"]["fin"], p["test"]["debut"])
        self.assertGreater(self.resultats["donnees"]["ecartes_par_la_garde"], 0)

    def test_chaque_horizon_a_cinq_methodes_et_un_verdict(self):
        self.assertEqual(set(self.resultats["horizons"]), {"5", "15", "30"})
        for bloc in self.resultats["horizons"].values():
            self.assertEqual(set(bloc["test"]), {"persistance", "moyenne_glissante", "naif_saisonnier", "ridge", "hist_gradient_boosting"})
            self.assertIn(bloc["meilleur_modele"], ("ridge", "hist_gradient_boosting"))
            self.assertEqual(set(bloc["ecarts"]), {"persistance", "moyenne_glissante", "naif_saisonnier"})

    def test_sur_un_profil_journalier_le_naif_saisonnier_est_tres_bon_et_le_modele_aussi(self):
        for bloc in self.resultats["horizons"].values():
            self.assertLess(bloc["test"]["naif_saisonnier"]["mae"], bloc["test"]["moyenne_glissante"]["mae"])
            self.assertLess(bloc["test"]["hist_gradient_boosting"]["mae"], bloc["test"]["persistance"]["mae"] + 0.5)

    def test_le_run_simule_applique_les_modeles_deja_appris_et_marque_le_naif_non_applicable(self):
        pas = 72
        t = np.arange(pas)
        vitesses = np.stack([25 + 5 * np.sin(t / 10 + k) for k in range(3)], axis=1)
        instants = (1_792_483_200 + 300 * (t + 1)).astype(np.int64) * 1000
        sim = Serie("sim", instants, ("a", "b", "c"), vitesses)
        r = rapport.evaluer_simule([sim], self.choisis, progres=lambda _: None)
        for horizon, bloc in r["horizons"].items():
            self.assertIsNone(bloc["methodes"]["naif_saisonnier"])
            self.assertGreater(bloc["n"], 0)
            self.assertIn("mae", bloc["methodes"]["ridge"])

    def test_les_chiffres_sont_deterministes(self):
        from prevision import modeles

        autre, _ = rapport.evaluer_metr_la(self.serie, progres=lambda _: None, pas_apprentissage=2)
        self.assertEqual(autre["horizons"]["15"]["test"], self.resultats["horizons"]["15"]["test"])

    def test_le_markdown_donne_les_trois_horizons_et_dit_non_applicable(self):
        pas = 72
        t = np.arange(pas)
        sim = Serie("sim", (1_792_483_200 + 300 * (t + 1)).astype(np.int64) * 1000, ("a", "b"), np.stack([25 + 3 * np.sin(t / 7 + k) for k in range(2)], axis=1))
        complet = {**self.resultats, "simule": rapport.evaluer_simule([sim], self.choisis, progres=lambda _: None),
                   "protocole": {"pas_apprentissage": 2}}
        texte = rapport.markdown(complet)
        for titre in ("5 min", "15 min", "30 min", "non applicable", "## Run simulé", "Bat la référence", "Biais moyen"):
            self.assertIn(titre, texte)
        self.assertNotIn(str(support.RACINE), texte)


@unittest.skipUnless(OUTILS, "numpy et scikit-learn absents")
class RunSimule(unittest.TestCase):
    def test_un_run_du_simulateur_devient_une_serie_de_5_minutes_en_mph(self):
        from anomalies import campagne
        from jeu_entrainement.catalogue import RunSpec

        banc = campagne.executer(RunSpec("ia10-test", "heure-de-pointe", 5, "evaluation", "07:00", 1800), campagne.EVALUATION)
        s = serie_depuis_un_run(banc)
        self.assertEqual(s.vitesses.shape, (6, 24))
        self.assertTrue(np.all(np.diff(s.instants_ms) == MS_PAR_PAS))
        valides = s.vitesses[~np.isnan(s.vitesses)]
        self.assertTrue(valides.size)
        self.assertLess(valides.max(), 50 / 1.609344 + 1)  # jamais plus que la vitesse limite la plus haute, convertie en mph


class PointDEntree(unittest.TestCase):
    def test_codes_de_sortie(self):
        from prevision import __main__ as principal

        with mock.patch.object(source, "verifier", return_value=Path("/x")), mock.patch("sys.stdout"):
            self.assertEqual(principal.main(["verifier"]), 0)
        with mock.patch.object(source, "telecharger", return_value=Path("/x")), mock.patch("sys.stdout"):
            self.assertEqual(principal.main(["telecharger"]), 0)
        with mock.patch.object(source, "verifier", side_effect=source.FichierRefuse("absent")), mock.patch("sys.stderr"):
            self.assertEqual(principal.main(["verifier"]), 1)
        with mock.patch.object(source, "telecharger", side_effect=OSError("réseau coupé")), mock.patch("sys.stderr"):
            self.assertEqual(principal.main(["telecharger"]), 1)

    @unittest.skipUnless(OUTILS, "numpy et scikit-learn absents")
    def test_evaluer_ecrit_les_resultats_ou_refuse(self):
        from prevision import __main__ as principal

        with mock.patch.object(rapport, "ecrire") as ecrire, mock.patch("sys.stdout"):
            self.assertEqual(principal.main(["evaluer"]), 0)
        ecrire.assert_called_once()
        with mock.patch.object(rapport, "ecrire", side_effect=source.FichierRefuse("fichier changé")), mock.patch("sys.stderr"):
            self.assertEqual(principal.main(["evaluer"]), 1)


@unittest.skipUnless(OUTILS and h5py is not None, "h5py absent : python3 scripts/dev/dev.py ml-env")
class LectureDuHdf5(unittest.TestCase):
    def ecrire(self, chemin, instants_ns, valeurs):
        with h5py.File(chemin, "w") as f:
            g = f.create_group("df")
            g.create_dataset("axis1", data=np.asarray(instants_ns, dtype=np.int64))
            g.create_dataset("axis0", data=np.array([b"111", b"222"]))
            g.create_dataset("block0_values", data=np.asarray(valeurs, dtype=np.float64))

    def test_les_zeros_deviennent_des_manquants_et_les_instants_des_millisecondes(self):
        from prevision.donnees import charger_metr_la

        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "petit.h5"
            pas_ns = 300 * 1_000_000_000
            self.ecrire(chemin, [0, pas_ns, 2 * pas_ns], [[60, 0], [0, 55], [50, 52]])
            s = charger_metr_la(chemin)
        self.assertEqual(s.capteurs, ("111", "222"))
        self.assertEqual(s.instants_ms.tolist(), [0, 300_000, 600_000])
        self.assertEqual(int(np.isnan(s.vitesses).sum()), 2)
        self.assertEqual(s.vitesses[2].tolist(), [50.0, 52.0])

    def test_des_instants_irreguliers_sont_refuses(self):
        from prevision.donnees import charger_metr_la

        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "irregulier.h5"
            self.ecrire(chemin, [0, 300 * 10**9, 700 * 10**9], [[1, 2], [3, 4], [5, 6]])
            with self.assertRaisesRegex(ValueError, "réguliers"):
                charger_metr_la(chemin)

    def test_une_forme_inattendue_est_refusee(self):
        from prevision.donnees import charger_metr_la

        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "forme.h5"
            self.ecrire(chemin, [0, 300 * 10**9], [[1, 2, 3], [4, 5, 6]])
            with self.assertRaisesRegex(ValueError, "forme"):
                charger_metr_la(chemin)


if __name__ == "__main__":
    unittest.main()
