"""Catalogue et découpage : aucun run commun entre entraînement, validation et test (critère de l'issue IA-08)."""

import dataclasses
import itertools
import unittest

from tests import support  # noqa: F401

from jeu_entrainement import catalogue as cat
from jeu_entrainement import simulation


class CatalogueDuJeu(unittest.TestCase):
    def test_le_catalogue_est_valide(self):
        cat.verifier()

    def test_les_trois_scenarios_de_l_adr_027_sont_la(self):
        self.assertEqual({r.scenario_id for r in cat.CATALOGUE}, {"journee-calme", "heure-de-pointe", "incident-ponctuel"})

    def test_capteur_muet_retard_et_doublon_sont_injectes_dans_plusieurs_runs(self):
        for type_ in cat.TYPES_D_ANOMALIE:
            ceux = [r for r in cat.CATALOGUE if type_ in r.types_d_anomalie]
            self.assertGreaterEqual(len(ceux), 3, type_)
            self.assertGreaterEqual(len({r.scenario_id for r in ceux}), 2, f"{type_} dans au moins deux scénarios")

    def test_aucun_run_id_n_est_commun_a_deux_ensembles(self):
        ensembles = {e: {r.run_id for r in runs} for e, runs in cat.par_ensemble().items()}
        for a, b in itertools.combinations(cat.ENSEMBLES, 2):
            self.assertEqual(ensembles[a] & ensembles[b], set(), f"{a} et {b} partagent un run")
        self.assertEqual(sum(len(v) for v in ensembles.values()), len(cat.CATALOGUE), "un run dans exactement un ensemble")

    def test_aucune_graine_n_est_commune_a_deux_ensembles(self):
        graines = {e: {r.seed for r in runs} for e, runs in cat.par_ensemble().items()}
        for a, b in itertools.combinations(cat.ENSEMBLES, 2):
            self.assertEqual(graines[a] & graines[b], set())
        self.assertEqual(len({r.seed for r in cat.CATALOGUE}), len(cat.CATALOGUE))

    def test_chaque_ensemble_contient_les_trois_scenarios(self):
        for ensemble, runs in cat.par_ensemble().items():
            self.assertEqual({r.scenario_id for r in runs}, set(cat.SCENARIOS), ensemble)

    def test_chaque_ensemble_a_une_part_utile_des_runs(self):
        taille = {e: len(r) for e, r in cat.par_ensemble().items()}
        self.assertGreater(taille[cat.TRAIN], taille[cat.VALIDATION])
        self.assertGreater(taille[cat.TRAIN], taille[cat.TEST])

    def test_chaque_ensemble_voit_au_moins_une_anomalie_et_un_run_sans_anomalie_ou_presque(self):
        for ensemble, runs in cat.par_ensemble().items():
            self.assertTrue(any(r.anomalies for r in runs), ensemble)

    def test_les_scenarios_du_catalogue_existent_dans_le_simulateur(self):
        _, _, _, scenarios = simulation.importer_le_simulateur()
        self.assertTrue(set(cat.SCENARIOS) <= set(scenarios.SCENARIOS))

    def test_chaque_anomalie_se_lit_avec_l_analyseur_du_simulateur(self):
        anomalies, _, _, _ = simulation.importer_le_simulateur()
        from datetime import UTC, datetime

        for run in cat.CATALOGUE:
            heures, minutes = (int(x) for x in run.debut.split(":"))
            debut = datetime(2026, 10, 20, heures, minutes, tzinfo=UTC)
            for texte in run.anomalies:
                anomalie = anomalies.parse_spec(texte, debut)
                self.assertGreaterEqual(anomalie.start, debut, run.run_id)
                self.assertLess(anomalie.last.timestamp(), debut.timestamp() + run.duree_s, f"{run.run_id} : l'anomalie tient dans le run")

    def test_un_retard_depasse_ce_que_le_traitement_corrige(self):
        """Sous une minute et demie de retard, le moteur de fenêtres met la fenêtre à jour : l'anomalie ne se verrait pas."""
        anomalies, _, _, _ = simulation.importer_le_simulateur()
        from datetime import UTC, datetime

        for run in cat.CATALOGUE:
            for texte in run.anomalies:
                if texte.startswith("retard"):
                    self.assertGreaterEqual(anomalies.parse_spec(texte, datetime(2026, 10, 20, tzinfo=UTC)).delay_s, 100, run.run_id)

    def test_les_run_id_sont_acceptes_par_le_simulateur(self):
        _, _, run, _ = simulation.importer_le_simulateur()
        for spec in cat.CATALOGUE:
            self.assertRegex(spec.run_id, run.RUN_ID.pattern)


class Verification(unittest.TestCase):
    def modifie(self, indice, **changements):
        catalogue = list(cat.CATALOGUE)
        catalogue[indice] = dataclasses.replace(catalogue[indice], **changements)
        return tuple(catalogue)

    def test_un_run_dans_deux_ensembles_est_refuse(self):
        doublon = dataclasses.replace(cat.CATALOGUE[0], ensemble=cat.TEST, seed=999)
        with self.assertRaises(cat.CatalogueInvalide) as contexte:
            cat.verifier(cat.CATALOGUE + (doublon,))
        self.assertIn("run_id en double", str(contexte.exception))

    def test_une_graine_reutilisee_dans_un_autre_ensemble_est_refusee(self):
        with self.assertRaises(cat.CatalogueInvalide) as contexte:
            cat.verifier(self.modifie(3, seed=cat.CATALOGUE[0].seed))
        self.assertIn("graine en double", str(contexte.exception))

    def test_un_ensemble_qui_manque_un_scenario_est_refuse(self):
        sans_incident_en_test = tuple(r for r in cat.CATALOGUE if not (r.ensemble == cat.TEST and r.scenario_id == "incident-ponctuel"))
        with self.assertRaises(cat.CatalogueInvalide) as contexte:
            cat.verifier(sans_incident_en_test)
        self.assertIn("incident-ponctuel", str(contexte.exception))

    def test_un_ensemble_vide_est_refuse(self):
        with self.assertRaises(cat.CatalogueInvalide) as contexte:
            cat.verifier(tuple(r for r in cat.CATALOGUE if r.ensemble != cat.VALIDATION))
        self.assertIn("vide", str(contexte.exception))

    def test_un_ensemble_inconnu_une_duree_fausse_et_un_scenario_inconnu_sont_refuses(self):
        for changement in ({"ensemble": "essai"}, {"duree_s": 90}, {"duree_s": 0}, {"scenario_id": "autre"}):
            with self.subTest(changement), self.assertRaises(cat.CatalogueInvalide):
                cat.verifier(self.modifie(0, **changement))


if __name__ == "__main__":
    unittest.main()
