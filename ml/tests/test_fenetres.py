"""Fenêtres d'une minute rejouées dans le moteur du traitement en flux : mêmes règles que l'entrepôt."""

import unittest
from decimal import Decimal

from tests import support  # noqa: F401

from jeu_entrainement import catalogue as cat
from jeu_entrainement import fenetres, simulation


def executer(scenario="incident-ponctuel", debut="08:00", duree=900, anomalies=(), graine=5):
    spec = cat.RunSpec("t-fenetres", scenario, graine, cat.TRAIN, debut, duree, tuple(anomalies))
    resultat = simulation.executer(spec)
    toutes, stats = fenetres.calculer(resultat)
    return resultat, toutes, stats


class Fenetres(unittest.TestCase):
    def test_une_fenetre_par_troncon_et_par_minute_avec_toutes_les_mesures(self):
        resultat, toutes, stats = executer(duree=600)
        self.assertEqual(len(toutes), 24 * 10)
        self.assertEqual({w.sample_count for w in toutes.values()}, {6})  # un capteur par tronçon, une mesure toutes les 10 s
        self.assertEqual(stats["accepted"], len(resultat.livraisons))

    def test_les_fenetres_sont_alignees_sur_la_minute_et_contigues(self):
        _, toutes, _ = executer(duree=600)
        for (_, debut), fenetre in toutes.items():
            self.assertEqual(debut % 60_000, 0)
            self.assertEqual(fenetre.size_s, 60)
        par_troncon = {}
        for troncon, debut in toutes:
            par_troncon.setdefault(troncon, []).append(debut)
        for debuts in par_troncon.values():
            debuts.sort()
            self.assertEqual([b - a for a, b in zip(debuts, debuts[1:], strict=False)], [60_000] * 9)

    def test_vehicules_vitesse_ponderee_et_occupation_se_recalculent_a_la_main(self):
        resultat, toutes, _ = executer(duree=300)
        troncon, debut = "ROAD_005", min(d for t, d in toutes if t == "ROAD_005")
        mesures = [
            livraison.event["data"] for livraison in resultat.livraisons
            if livraison.event["data"]["road_segment_id"] == troncon
            and debut <= fenetres.epoch_ms(livraison.event["time"]) - 10_000 < debut + 60_000
        ]
        fenetre = toutes[(troncon, debut)]
        self.assertEqual(len(mesures), 6)
        self.assertEqual(fenetre.vehicle_count, sum(m["vehicle_count"] for m in mesures))
        poids = sum(m["vehicle_count"] for m in mesures if m["average_speed_kmh"] is not None)
        somme = sum(Decimal(repr(m["average_speed_kmh"])) * m["vehicle_count"] for m in mesures if m["average_speed_kmh"] is not None)
        self.assertEqual(fenetre.exact_average_speed, somme / poids)
        self.assertEqual(fenetre.exact_occupancy, sum(Decimal(repr(m["occupancy_rate"])) for m in mesures) / 6)

    def test_un_capteur_muet_donne_des_fenetres_vides_et_les_autres_restent_pleines(self):
        _, toutes, stats = executer(anomalies=("muet:sensor=SENSOR_003,at=+300,duration=3m",), duree=900)
        vides = [(t, d) for (t, d), w in toutes.items() if w.sample_count == 0]
        self.assertTrue(vides)
        self.assertEqual({t for t, _ in vides}, {"ROAD_003"})
        for cle in vides:
            self.assertEqual((toutes[cle].vehicle_count, toutes[cle].exact_average_speed), (0, None))
        self.assertGreaterEqual(stats["empty_windows"], 2)
        autres = [w for (t, _), w in toutes.items() if t != "ROAD_003"]
        self.assertEqual({w.sample_count for w in autres}, {6})

    def test_un_doublon_n_est_compte_qu_une_fois(self):
        resultat, toutes, stats = executer(anomalies=("doublon:sensor=SENSOR_001,at=+120,duration=5m,copies=2,lag=3",))
        self.assertEqual(stats["duplicates"], 2 * 30)  # 30 intervalles de 10 s, 2 copies chacun
        self.assertEqual({w.sample_count for w in toutes.values()}, {6})
        self.assertGreater(len(resultat.livraisons), 24 * 90)

    def test_un_retard_au_dela_de_ce_que_le_traitement_corrige_retire_la_mesure_de_sa_fenetre(self):
        _, toutes, stats = executer(anomalies=("retard:sensor=SENSOR_002,at=+300,duration=3m,delay=120",), duree=900)
        self.assertGreater(stats["late"], 0)
        incompletes = [w for (t, _), w in toutes.items() if w.sample_count < 6]
        self.assertTrue(incompletes)
        self.assertEqual({w.road_segment_id for w in incompletes}, {"ROAD_002"})

    def test_une_mesure_suspecte_est_exclue_des_fenetres(self):
        _, toutes, stats = executer(anomalies=("aberrante:sensor=SENSOR_004,at=+300,duration=1m,variant=vitesse",))
        self.assertEqual(stats["excluded"], 6)
        comptes = [w.sample_count for (t, _), w in toutes.items() if t == "ROAD_004"]
        self.assertEqual(sum(comptes), 6 * len(comptes) - 6)  # les six mesures suspectes ne sont dans aucune fenêtre
        self.assertLess(min(comptes), 6)

    def test_deux_executions_donnent_les_memes_fenetres(self):
        _, a, _ = executer()
        _, b, _ = executer()
        self.assertEqual({k: (w.vehicle_count, w.exact_average_speed, w.exact_occupancy) for k, w in a.items()},
                         {k: (w.vehicle_count, w.exact_average_speed, w.exact_occupancy) for k, w in b.items()})

    def test_le_rapport_de_vitesse_est_celui_du_traitement_en_flux(self):
        """Contrôle croisé avec `app.flux.indicators` quand ses dépendances (pydantic) sont installées."""
        try:
            fenetres.importer_le_moteur()
            from app.flux.indicators import speed_ratio
            from app.flux.model import Referential, SegmentRef
        except ImportError:
            self.skipTest("les dépendances du service de traitement (pydantic) ne sont pas installées")
        from jeu_entrainement import lignes

        resultat, toutes, _ = executer(duree=600)
        _, reseau, _, _ = simulation.importer_le_simulateur()
        referentiel = Referential(segments={s.road_segment_id: SegmentRef(s.road_segment_id, i, s.intersection_id, float(s.free_flow_speed_kmh)) for i, s in enumerate(reseau.SEGMENTS)})
        for (troncon, _), fenetre in list(toutes.items())[:60]:
            attendu = speed_ratio(fenetre, referentiel)
            self.assertEqual(lignes.rapport_de_vitesse(fenetre.exact_average_speed, reseau.SEGMENT_BY_ID[troncon].free_flow_speed_kmh), attendu)


if __name__ == "__main__":
    unittest.main()
