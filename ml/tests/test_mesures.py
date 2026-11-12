"""Métriques du cadrage ML : cas calculés à la main, puis la règle de l'ADR-028 sur de petites séries et sur le jeu v1."""

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tests import support  # noqa: F401 : chemins d'import

from jeu_entrainement import parquet
from mesures import metriques as m
from mesures import reference
from mesures.__main__ import main

F, S, C = "FREE_FLOW", "SLOW", "CONGESTED"


def serie(*blocs):
    """`serie((F, 5), (C, 3))` : cinq minutes fluides puis trois minutes congestionnées."""
    return [etat for etat, n in blocs for _ in range(n)]


class TestF1(unittest.TestCase):
    def test_exemple_calcule_a_la_main(self):
        vrais = [F, F, F, F, S, S, C, C, C, C]
        predits = [F, F, F, S, S, C, C, C, C, F]
        r = m.f1_par_classe(vrais, predits)
        self.assertAlmostEqual(r[F][0], 3 / 4)  # annoncés F : 4, justes : 3
        self.assertAlmostEqual(r[F][1], 3 / 4)  # réels F : 4, retrouvés : 3
        self.assertAlmostEqual(r[S][0], 1 / 2)
        self.assertAlmostEqual(r[S][1], 1 / 2)
        self.assertAlmostEqual(r[C][0], 3 / 4)
        self.assertAlmostEqual(r[C][1], 3 / 4)
        self.assertAlmostEqual(m.f1_macro(vrais, predits), (0.75 + 0.5 + 0.75) / 3)
        self.assertAlmostEqual(m.rappel_congested(vrais, predits), 0.75)

    def test_parfait(self):
        vrais = serie((F, 3), (S, 2), (C, 2))
        self.assertEqual(m.f1_macro(vrais, vrais), 1.0)

    def test_toujours_fluide_donne_un_tiers_environ(self):
        vrais = serie((F, 90), (S, 5), (C, 5))
        self.assertLess(m.f1_macro(vrais, [F] * 100), 0.33)
        self.assertEqual(m.rappel_congested(vrais, [F] * 100), 0.0)

    def test_un_run_sans_congestion_ne_dit_rien_du_f1(self):
        """Un seul état dans les vrais : le F1 macro vaut 1/3 même pour une réponse parfaite, d'où la mesure sur l'ensemble réuni."""
        vrais = [F] * 50
        self.assertAlmostEqual(m.f1_macro(vrais, vrais), 1 / 3)

    def test_longueurs_differentes_refusees(self):
        with self.assertRaises(ValueError):
            m.f1_par_classe([F], [F, F])
        with self.assertRaises(ValueError):
            m.apparier([F], [F, F])


class TestEpisodesEtAlertes(unittest.TestCase):
    def test_episodes_et_entrees(self):
        etats = serie((F, 3), (C, 2), (S, 1), (C, 2))
        self.assertEqual(m.episodes(etats), [(3, 5), (6, 8)])
        self.assertEqual(m.entrees(etats), [3, 6])
        self.assertEqual(m.entrees([C, C, F]), [0])  # la première minute compte

    def test_delai_de_detection(self):
        vrais = serie((F, 10), (C, 10), (F, 10))
        predits = serie((F, 12), (C, 8), (F, 10))  # alerte à la minute 12 : épisode commencé à la minute 10
        a = m.apparier(vrais, predits)
        self.assertEqual((a.episodes, a.manques, a.alertes, a.fausses), (1, 0, 1, 0))
        self.assertEqual(a.delais, [2])

    def test_alerte_en_avance_donne_delai_nul(self):
        vrais = serie((F, 20), (C, 5), (F, 5))
        predits = serie((F, 17), (C, 8), (F, 5))  # 3 minutes avant le début réel
        a = m.apparier(vrais, predits)
        self.assertEqual((a.delais, a.fausses), ([0], 0))

    def test_episode_manque(self):
        a = m.apparier(serie((F, 5), (C, 5)), [F] * 10)
        self.assertEqual((a.episodes, a.manques, a.delais, a.alertes), (1, 1, [], 0))

    def test_alerte_hors_episode_est_fausse(self):
        a = m.apparier([F] * 100, serie((F, 50), (C, 3), (F, 47)))
        self.assertEqual((a.alertes, a.fausses, a.episodes), (1, 1, 0))

    def test_alerte_trop_en_avance_est_fausse(self):
        vrais = serie((F, 40), (C, 5), (F, 5))
        predits = serie((F, 20), (C, 2), (F, 18), (C, 5), (F, 5))  # une alerte 20 minutes avant, une à l'heure
        a = m.apparier(vrais, predits)
        self.assertEqual((a.alertes, a.fausses, a.delais), (2, 1, [0]))

    def test_etat_qui_clignote_compte_des_fausses_alertes(self):
        """Un même épisode annoncé quatre fois : la première alerte est juste, les trois suivantes sont fausses."""
        vrais = serie((F, 5), (C, 20), (F, 5))
        predits = serie((F, 5), (C, 3), (S, 1), (C, 3), (S, 1), (C, 3), (S, 1), (C, 8), (F, 5))
        a = m.apparier(vrais, predits)
        self.assertEqual((a.alertes, a.fausses, a.manques), (4, 3, 0))

    def test_une_alerte_ne_sert_qu_a_un_episode(self):
        """Deux épisodes à 3 minutes d'écart et une seule alerte : le second épisode est manqué."""
        vrais = serie((F, 5), (C, 5), (F, 3), (C, 5), (F, 5))
        predits = serie((F, 5), (C, 5), (F, 13))
        a = m.apparier(vrais, predits)
        self.assertEqual((a.episodes, a.manques, a.alertes, a.fausses), (2, 1, 1, 0))

    def test_fausses_alertes_par_troncon_et_jour(self):
        a = m.Alertes(fausses=3, minutes=2 * m.MINUTES_PAR_JOUR)
        self.assertAlmostEqual(a.fausses_par_troncon_et_jour, 1.5)
        self.assertEqual(m.Alertes().fausses_par_troncon_et_jour, 0.0)

    def test_mesurer_reunit_les_series(self):
        s1 = (serie((F, 5), (C, 5)), serie((F, 5), (C, 5)))
        s2 = (serie((F, 10)), serie((F, 10)))
        r = m.mesurer([s1, s2])
        self.assertEqual(r.alertes.minutes, 20)
        self.assertEqual(r.alertes.episodes, 1)
        self.assertEqual(r.rappel_congested, 1.0)
        self.assertEqual(set(r.en_dict()), {
            "f1_macro", "rappel_congested", "precision_congested", "par_classe", "episodes", "episodes_manques",
            "delai_median_min", "delai_max_min", "alertes", "fausses_alertes", "fausses_alertes_par_troncon_et_jour",
            "troncons_jours"})


def minutes(ratios):
    """Des lignes comme celles de `charger` : (run, tronçon, début, véhicules, ratio, label) ; le label n'est pas utilisé."""
    return [("r", "T", 60_000 * i, 10, ratio, F) for i, ratio in enumerate(ratios)]


class TestRegle(unittest.TestCase):
    def test_une_serie_qui_oscille_autour_du_seuil_donne_au_plus_une_transition(self):
        """Exigence EXG-TRA-03 vue du côté de la mesure : 0,62 et 0,58 en alternance (seuil 0,60) ne font pas clignoter."""
        ratios = [0.9] * 5 + [0.62, 0.58] * 10 + [0.9] * 5
        etats = reference.etats_de_la_regle(minutes(ratios))
        transitions = sum(1 for a, b in zip(etats, etats[1:], strict=False) if a != b)
        self.assertLessEqual(transitions, 1)

    def test_deux_fenetres_pour_descendre_trois_pour_remonter(self):
        ratios = [0.9] * 3 + [0.3] * 2 + [0.9] * 2 + [0.9] * 3
        etats = reference.etats_de_la_regle(minutes(ratios))
        self.assertEqual(etats[3], F)
        self.assertEqual(etats[4], C)  # 2e fenêtre sous 0,35
        self.assertEqual(etats[6], C)  # remontée : 2 fenêtres au-dessus de 0,70 ne suffisent pas
        self.assertEqual(etats[7], F)  # 3e fenêtre

    def test_route_vide_est_fluide(self):
        lignes = [("r", "T", 60_000 * i, 0, None, F) for i in range(6)]
        self.assertEqual(set(reference.etats_de_la_regle(lignes)), {F})

    def test_sans_duree_minimale_les_alertes_se_multiplient(self):
        """Ce que la stabilité achète : sans elle, la même série fait clignoter l'état."""
        ratios = [0.9] * 5 + [0.3, 0.9] * 8 + [0.9] * 5
        vrais = [F] * len(ratios)
        stable = m.apparier(vrais, reference.etats_de_la_regle(minutes(ratios)))
        *_, par_defaut, _ = reference.importer_la_regle()
        import dataclasses

        nerveux = m.apparier(vrais, reference.etats_de_la_regle(
            minutes(ratios), dataclasses.replace(par_defaut, degrade_windows=1, recover_windows=1)))
        self.assertEqual(stable.alertes, 0)
        self.assertGreaterEqual(nerveux.alertes, 8)


class TestEnsembleTest(unittest.TestCase):
    def test_le_test_n_est_pas_lisible(self):
        with self.assertRaises(reference.EnsembleReserve):
            reference.charger("test", Path("n'importe/où"))

    def test_la_ligne_de_commande_refuse_le_test(self):
        tampon = StringIO()
        from contextlib import redirect_stderr

        with redirect_stderr(tampon):
            self.assertEqual(main(["--ensemble", "test"]), 1)
        self.assertIn("réservé", tampon.getvalue())

    def test_reunir_refuse_une_serie_dans_deux_ensembles(self):
        with self.assertRaises(ValueError):
            reference.reunir({("r", "T"): []}, {("r", "T"): []})


@unittest.skipUnless((reference.DOSSIER_JEU / "train.parquet").is_file(), "jeu v1 absent : python3 ml/src/construire_jeu.py")
class TestSurLeJeu(unittest.TestCase):
    """Les valeurs que `cadrage-ml.md` cite : si elles changent, le cadrage doit être relu."""

    @classmethod
    def setUpClass(cls):
        cls.series = reference.reunir(reference.charger("train"), reference.charger("validation"))

    def test_la_regle_sur_train_et_validation(self):
        r = reference.mesurer_la_regle(self.series)
        self.assertAlmostEqual(r.f1_macro, 0.9761, delta=0.0005)
        self.assertAlmostEqual(r.rappel_congested, 0.9745, delta=0.0005)
        self.assertEqual((r.alertes.episodes, r.alertes.manques), (27, 0))
        self.assertEqual(r.alertes.delai_median, 1)
        self.assertLessEqual(r.alertes.fausses_par_troncon_et_jour, 0.10)

    def test_sans_duree_minimale_le_f1_monte_mais_les_fausses_alertes_aussi(self):
        """Pourquoi l'acceptation exige les fausses alertes : le F1 seul récompense un état nerveux."""
        stable = reference.mesurer_la_regle(self.series)
        nerveux = reference.sans_hysteresis(self.series)
        self.assertGreater(nerveux.f1_macro, stable.f1_macro)
        self.assertGreater(nerveux.alertes.fausses_par_troncon_et_jour, 0.5)

    def test_la_ligne_de_commande_ecrit_un_rapport_json(self):
        sortie = StringIO()
        with redirect_stdout(sortie):
            code = main(["--json"])
        self.assertEqual(code, 0)
        rapport = json.loads(sortie.getvalue())
        self.assertEqual(set(rapport), {"train", "validation", "train+validation"})
        self.assertIn("f1_macro", rapport["train"]["regle"])

    def test_les_classes_du_jeu_sont_celles_de_la_mesure(self):
        _, lignes = parquet.lire(reference.DOSSIER_JEU / "validation.parquet")
        self.assertEqual({ligne[-3] for ligne in lignes}, set(m.ETATS))


if __name__ == "__main__":
    unittest.main()
