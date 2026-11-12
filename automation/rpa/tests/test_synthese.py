import unittest
from datetime import UTC, datetime

from tests.donnees import indicateur, jeu

from rapport import api, periode, synthese

SEMAINE = periode.semaine_de(datetime(2026, 10, 22, tzinfo=UTC).date())


def resumer(lignes, tronque=False):
    return synthese.resumer(api.Indicateurs(lignes, tronque), SEMAINE)


class Synthese(unittest.TestCase):
    def test_les_totaux_et_les_troncons_sont_comptes(self):
        resume = resumer(jeu(3, 12))
        self.assertEqual((resume.fenetres, [t.identifiant for t in resume.troncons]), (36, ["ROAD_001", "ROAD_002", "ROAD_003"]))
        self.assertEqual(resume.etats, {"FREE_FLOW": 27, "CONGESTED": 6, "SLOW": 3})

    def test_les_parts_se_calculent_par_troncon(self):
        par_id = {t.identifiant: t for t in resumer(jeu(3, 12)).troncons}
        self.assertEqual(par_id["ROAD_001"].part_congestion, 0.0)
        self.assertEqual(par_id["ROAD_002"].part_congestion, 0.5)
        self.assertEqual(par_id["ROAD_003"].part_ralenti, 0.25)
        self.assertAlmostEqual(par_id["ROAD_002"].ratio_moyen, (0.3 + 0.9) / 2)

    def test_un_etat_inconnu_n_entre_pas_dans_les_parts_et_un_ratio_vide_est_ignore(self):
        lignes = [indicateur(minute=0, etat="UNKNOWN", ratio=None), indicateur(minute=1, etat="CONGESTED", ratio=0.2)]
        (troncon,) = resumer(lignes).troncons
        self.assertEqual((troncon.fenetres, troncon.part_congestion, troncon.ratio_moyen), (2, 1.0, 0.2))

    def test_un_troncon_sans_aucun_ratio_a_une_moyenne_absente_et_non_zero(self):
        (troncon,) = resumer([indicateur(etat="UNKNOWN", ratio=None)]).troncons
        self.assertIsNone(troncon.ratio_moyen)
        self.assertEqual(troncon.part_congestion, 0.0)

    def test_la_provenance_simulee_est_dite(self):
        self.assertTrue(resumer(jeu()).simule)
        self.assertEqual(resumer(jeu()).sources, ["SIMULATED"])
        reel = resumer([indicateur(source="REAL_LIVE")])
        self.assertFalse(reel.simule)

    def test_un_melange_de_sources_reste_simule(self):
        self.assertTrue(resumer([indicateur(source="REAL_LIVE"), indicateur(minute=1, source="SIMULATED")]).simule)

    def test_les_executions_et_scenarios_sont_listes_sans_doublon(self):
        lignes = jeu() + [indicateur(run="autre", minute=99)]
        resume = resumer(lignes)
        self.assertEqual(resume.runs, ["autre", "run-demo"])
        self.assertEqual(resume.scenarios, ["heure-de-pointe"])

    def test_premiere_et_derniere_fenetre(self):
        resume = resumer(jeu(1, 12))
        self.assertEqual((resume.premiere, resume.derniere), ("2026-10-19T06:00:00Z", "2026-10-19T06:55:00Z"))

    def test_aucune_donnee_donne_une_synthese_vide_sans_erreur(self):
        resume = resumer([])
        self.assertEqual((resume.fenetres, resume.troncons, resume.etats, resume.premiere), (0, [], {}, None))
        self.assertIsNone(resume.completude_moyenne)

    def test_le_drapeau_de_troncature_est_conserve(self):
        self.assertTrue(resumer(jeu(), tronque=True).tronque)


if __name__ == "__main__":
    unittest.main()
