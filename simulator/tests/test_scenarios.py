"""Scénarios, vérité terrain et plausibilité des mesures."""

import json
import statistics
import unittest
from datetime import UTC, datetime

from helpers import config, play

from novaria_sim.network import SEGMENT_BY_ID, SEGMENT_BY_SENSOR, SEGMENTS
from novaria_sim.scenarios import CONGESTED, FREE_FLOW, SCENARIOS, SLOW, demand_factor, hm


def etat(scenario, road, heure):
    instant = datetime(2026, 10, 20, int(heure[:2]), int(heure[3:]), tzinfo=UTC)
    return SCENARIOS[scenario].label_state(SEGMENT_BY_ID[road], instant)


class Calendrier(unittest.TestCase):
    def test_journee_calme_reste_fluide_toute_la_journee(self):
        for segment in SEGMENTS:
            for minute in range(0, 24 * 60, 5):
                instant = datetime(2026, 10, 20, minute // 60, minute % 60, tzinfo=UTC)
                self.assertEqual(SCENARIOS["journee-calme"].label_state(segment, instant), FREE_FLOW)

    def test_heure_de_pointe_sature_les_approches_nord_et_ouest(self):
        self.assertEqual(etat("heure-de-pointe", "ROAD_001", "08:00"), CONGESTED)  # artère, Nord
        self.assertEqual(etat("heure-de-pointe", "ROAD_004", "08:00"), CONGESTED)  # artère, Ouest
        self.assertEqual(etat("heure-de-pointe", "ROAD_009", "08:00"), CONGESTED)  # collectrice, Nord

    def test_heure_de_pointe_ralentit_seulement_les_approches_est_et_sud(self):
        for road in ("ROAD_002", "ROAD_003", "ROAD_010", "ROAD_011"):
            with self.subTest(road=road):
                self.assertEqual(etat("heure-de-pointe", road, "08:00"), SLOW)
        for segment in SEGMENTS:
            if segment.approach in ("E", "S"):
                for minute in range(0, 24 * 60, 5):
                    instant = datetime(2026, 10, 20, minute // 60, minute % 60, tzinfo=UTC)
                    self.assertNotEqual(SCENARIOS["heure-de-pointe"].label_state(segment, instant), CONGESTED)

    def test_heure_de_pointe_est_fluide_la_nuit_et_en_journee(self):
        for heure in ("03:00", "06:00", "11:30", "14:00", "22:00"):
            self.assertEqual(etat("heure-de-pointe", "ROAD_001", heure), FREE_FLOW, heure)

    def test_la_pointe_est_decalee_d_un_troncon_a_l_autre(self):
        debuts = set()
        for road in ("ROAD_001", "ROAD_004", "ROAD_005", "ROAD_008"):
            minute = next(m for m in range(6 * 60, 10 * 60) if etat("heure-de-pointe", road, f"{m // 60:02d}:{m % 60:02d}") == CONGESTED)
            debuts.add(minute)
        self.assertGreater(len(debuts), 1)

    def test_incident_sur_road_005_de_08h10_a_08h35(self):
        self.assertEqual(etat("incident-ponctuel", "ROAD_005", "08:05"), FREE_FLOW)
        self.assertEqual(etat("incident-ponctuel", "ROAD_005", "08:10"), CONGESTED)
        self.assertEqual(etat("incident-ponctuel", "ROAD_005", "08:34"), CONGESTED)
        self.assertEqual(etat("incident-ponctuel", "ROAD_005", "08:40"), SLOW)  # il se résorbe
        self.assertEqual(etat("incident-ponctuel", "ROAD_005", "09:00"), FREE_FLOW)

    def test_incident_les_autres_approches_du_carrefour_ralentissent_les_autres_carrefours_non(self):
        for road in ("ROAD_006", "ROAD_007", "ROAD_008"):
            self.assertEqual(etat("incident-ponctuel", road, "08:20"), SLOW)
        for road in ("ROAD_001", "ROAD_009", "ROAD_024"):
            self.assertEqual(etat("incident-ponctuel", road, "08:20"), FREE_FLOW)

    def test_la_demande_a_deux_pointes(self):
        nuit = demand_factor("ARTERIAL", hm("03:00"))
        matin = demand_factor("ARTERIAL", hm("08:00"))
        midi = demand_factor("ARTERIAL", hm("12:00"))
        soir = demand_factor("ARTERIAL", hm("17:00"))
        self.assertGreater(matin, 1.3 * midi)  # creux de journée à 70 % de la pointe
        self.assertGreater(soir, 1.3 * midi)
        self.assertGreater(midi, nuit)
        self.assertGreater(demand_factor("ARTERIAL", hm("08:00")), demand_factor("LOCAL", hm("08:00")))


class VeriteTerrain(unittest.TestCase):
    def test_une_ligne_par_capteur_et_par_intervalle(self):
        deliveries, truth, _ = play(config(minutes=5))
        self.assertEqual(len(truth), 24 * 30)
        self.assertEqual(len(deliveries), 24 * 30)

    def test_chaque_ligne_pointe_vers_son_message_et_porte_l_etat_voulu(self):
        deliveries, truth, _ = play(config(minutes=5, start=datetime(2026, 10, 20, 8, 0, tzinfo=UTC)))
        ids = {d.event["id"] for d in deliveries}
        for row in truth:
            self.assertIn(row["event_id"], ids)
            self.assertIn(row["label_state"], (FREE_FLOW, SLOW, CONGESTED))
            self.assertTrue(row["emitted"])
            self.assertEqual(row["anomalies"], [])
        self.assertIn(CONGESTED, {row["label_state"] for row in truth})

    def test_la_verite_terrain_vient_du_scenario_pas_de_la_regle_de_seuils(self):
        # Même scénario, deux graines : les mesures bruitées diffèrent, l'état voulu non (il n'est pas calculé depuis elles).
        _, a, _ = play(config(seed=5, start=datetime(2026, 10, 20, 8, 0, tzinfo=UTC)))
        _, b, _ = play(config(seed=6, start=datetime(2026, 10, 20, 8, 0, tzinfo=UTC)))
        self.assertEqual([x["label_state"] for x in a], [x["label_state"] for x in b])


class Plausibilite(unittest.TestCase):
    def setUp(self):
        self.deliveries, self.truth, _ = play(config("heure-de-pointe", minutes=90, start=datetime(2026, 10, 20, 7, 15, tzinfo=UTC)))
        self.state = {row["event_id"]: row["label_state"] for row in self.truth}

    def test_le_ratio_de_vitesse_suit_l_etat_voulu(self):
        ratios = {FREE_FLOW: [], SLOW: [], CONGESTED: []}
        for d in self.deliveries:
            data = d.event["data"]
            if data["average_speed_kmh"] is not None:
                limite = SEGMENT_BY_SENSOR[data["sensor_id"]].speed_limit_kmh
                ratios[self.state[d.event["id"]]].append(data["average_speed_kmh"] / limite)
        self.assertAlmostEqual(statistics.mean(ratios[FREE_FLOW]), 0.90, delta=0.03)
        self.assertAlmostEqual(statistics.mean(ratios[SLOW]), 0.50, delta=0.03)
        self.assertAlmostEqual(statistics.mean(ratios[CONGESTED]), 0.20, delta=0.03)

    def test_les_etats_voisins_se_chevauchent_donc_la_regle_de_seuils_n_est_pas_parfaite(self):
        lent = [d.event["data"]["average_speed_kmh"] / SEGMENT_BY_SENSOR[d.event["data"]["sensor_id"]].speed_limit_kmh
                for d in self.deliveries if self.state[d.event["id"]] == SLOW and d.event["data"]["average_speed_kmh"] is not None]
        self.assertTrue(any(r < 0.35 for r in lent) or any(r > 0.60 for r in lent))

    def test_la_vitesse_est_nulle_si_et_seulement_si_aucun_vehicule(self):
        for d in self.deliveries:
            data = d.event["data"]
            self.assertEqual(data["average_speed_kmh"] is None, data["vehicle_count"] == 0)

    def test_valeurs_dans_les_bornes_et_qualite_valide(self):
        for d in self.deliveries:
            data = d.event["data"]
            self.assertGreaterEqual(data["vehicle_count"], 0)
            self.assertTrue(0.0 <= data["occupancy_rate"] <= 1.0)
            self.assertTrue(0.0 <= data["queue_length_m"] <= SEGMENT_BY_SENSOR[data["sensor_id"]].length_m)
            self.assertEqual(data["quality"], {"status": "VALID"})
            if data["average_speed_kmh"] is not None:
                self.assertTrue(0.0 < data["average_speed_kmh"] <= 200.0)

    def test_aucune_mesure_normale_ne_declenche_la_regle_dq_05(self):
        # Les valeurs douteuses sont réservées aux anomalies demandées.
        for scenario, debut, minutes in (("heure-de-pointe", datetime(2026, 10, 20, 7, 0, tzinfo=UTC), 120),
                                         ("incident-ponctuel", datetime(2026, 10, 20, 7, 30, tzinfo=UTC), 90),
                                         ("journee-calme", datetime(2026, 10, 20, 0, 0, tzinfo=UTC), 240)):
            deliveries, _, _ = play(config(scenario, minutes=minutes, start=debut))
            for d in deliveries:
                data = d.event["data"]
                segment = SEGMENT_BY_SENSOR[data["sensor_id"]]
                self.assertLessEqual(data["vehicle_count"] * 6 / segment.lane_count, 40)
                if data["average_speed_kmh"] is not None:
                    self.assertLessEqual(data["average_speed_kmh"], 1.5 * segment.speed_limit_kmh)
                    self.assertFalse(data["vehicle_count"] > 0 and data["average_speed_kmh"] == 0)

    def test_le_trafic_suit_les_heures_de_pointe(self):
        def vehicules(heure, scenario="heure-de-pointe"):
            debut = datetime(2026, 10, 20, heure, 0, tzinfo=UTC)
            deliveries, _, _ = play(config(scenario, minutes=30, start=debut))
            return sum(d.event["data"]["vehicle_count"] for d in deliveries if d.event["data"]["sensor_id"] in ("SENSOR_001", "SENSOR_002"))

        self.assertGreater(vehicules(8), 3 * vehicules(3))

    def test_un_tronçon_sature_ecoule_moins_et_est_plus_occupe(self):
        sature = [d.event["data"] for d in self.deliveries if self.state[d.event["id"]] == CONGESTED and SEGMENT_BY_SENSOR[d.event["data"]["sensor_id"]].road_type == "ARTERIAL"]
        fluide = [d.event["data"] for d in self.deliveries if self.state[d.event["id"]] == FREE_FLOW and SEGMENT_BY_SENSOR[d.event["data"]["sensor_id"]].road_type == "ARTERIAL"]
        self.assertTrue(sature and fluide)
        self.assertGreater(statistics.mean(m["occupancy_rate"] for m in sature), statistics.mean(m["occupancy_rate"] for m in fluide))
        self.assertGreater(statistics.mean(m["queue_length_m"] for m in sature), statistics.mean(m["queue_length_m"] for m in fluide))
        self.assertEqual(statistics.mean(m["queue_length_m"] for m in fluide), 0.0)


class ScenariosDeclares(unittest.TestCase):
    def test_trois_scenarios_decrits(self):
        self.assertEqual(set(SCENARIOS), {"journee-calme", "heure-de-pointe", "incident-ponctuel"})
        for scenario in SCENARIOS.values():
            self.assertTrue(scenario.description)
            self.assertRegex(scenario.scenario_id, r"^[a-z0-9_-]{1,60}$")  # motif du contrat pour scenario_id
        json.dumps({s.scenario_id: s.start for s in SCENARIOS.values()})


if __name__ == "__main__":
    unittest.main()
