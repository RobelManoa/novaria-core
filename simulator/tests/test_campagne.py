"""La campagne : des jours aux calendriers différents, déterministes, sans toucher aux trois scénarios d'origine (IA-12)."""

import statistics
import unittest
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from helpers import config, play

from novaria_sim import model
from novaria_sim.network import SEGMENTS
from novaria_sim.scenarios import (
    CAMPAIGN_ID,
    CONGESTED,
    FREE_FLOW,
    SCENARIOS,
    SLOW,
    day_plan,
)

CAMPAGNE = SCENARIOS[CAMPAIGN_ID]
LUNDI, SAMEDI = date(2026, 10, 19), date(2026, 10, 24)


def etats(jour: date, pas_min: int = 10) -> Counter:
    n = Counter()
    for segment in SEGMENTS:
        for minute in range(0, 24 * 60, pas_min):
            instant = datetime(jour.year, jour.month, jour.day, minute // 60, minute % 60, tzinfo=UTC)
            n[CAMPAGNE.label_state(segment, instant)] += 1
    return n


class Calendrier(unittest.TestCase):
    def test_le_calendrier_d_un_jour_ne_depend_que_de_sa_date(self):
        day_plan.cache_clear()
        premier = day_plan(LUNDI)
        day_plan.cache_clear()
        self.assertEqual(day_plan(LUNDI), premier)

    def test_semaine_et_weekend_sont_reconnus(self):
        self.assertEqual({day_plan(LUNDI + timedelta(days=i)).kind for i in range(5)}, {"semaine"})
        self.assertEqual({day_plan(SAMEDI + timedelta(days=i)).kind for i in range(2)}, {"weekend"})

    def test_les_jours_ne_se_ressemblent_pas(self):
        """Sur 56 jours : des jours de pluie et des jours secs, des incidents, des échelles de demande et des décalages variés."""
        jours = [day_plan(LUNDI + timedelta(days=i)) for i in range(56)]
        self.assertEqual({j.weather for j in jours}, {"sec", "pluie"})
        self.assertGreater(len({j.scale for j in jours}), 40)
        self.assertGreater(len({j.shift_s for j in jours if j.kind == "semaine"}), 20)
        nombres = Counter(len(j.incidents) for j in jours)
        self.assertEqual(set(nombres), {0, 1, 2})
        self.assertGreater(len({i.road_segment_id for j in jours for i in j.incidents}), 10, "les incidents tombent sur des tronçons variés")

    def test_un_incident_est_dans_les_bornes_et_sur_un_troncon_du_reseau(self):
        ids = {s.road_segment_id for s in SEGMENTS}
        for i in range(120):
            for incident in day_plan(LUNDI + timedelta(days=i)).incidents:
                self.assertIn(incident.road_segment_id, ids)
                self.assertGreaterEqual(incident.start_s, 6 * 3600)
                self.assertLess(incident.start_s, 20 * 3600)
                self.assertEqual(incident.start_s % 300, 0)
                self.assertIn(incident.duration_s, range(15 * 60, 61 * 60, 300))

    def test_un_jour_de_semaine_sature_et_un_weekend_beaucoup_moins(self):
        semaine = sum(etats(LUNDI + timedelta(days=i))[CONGESTED] for i in range(5))
        weekend = sum(etats(SAMEDI + timedelta(days=i))[CONGESTED] for i in range(2))
        self.assertGreater(semaine / 5, 4 * weekend / 2)
        self.assertGreater(semaine, 0)

    def test_les_trois_etats_existent_sur_une_semaine(self):
        total = Counter()
        for i in range(7):
            total += etats(LUNDI + timedelta(days=i))
        self.assertEqual(set(total), {FREE_FLOW, SLOW, CONGESTED})
        self.assertGreater(total[FREE_FLOW], total[SLOW] + total[CONGESTED], "la plupart du temps, la circulation est fluide")

    def test_la_nuit_est_fluide_et_la_pointe_du_matin_charge_nord_et_ouest(self):
        nuit = datetime(2026, 10, 21, 3, 0, tzinfo=UTC)
        for segment in SEGMENTS:
            self.assertEqual(CAMPAGNE.label_state(segment, nuit), FREE_FLOW)
        jours = [LUNDI + timedelta(days=i) for i in range(5)]
        charge = {"N": 0, "W": 0, "E": 0, "S": 0}
        for jour in jours:
            for segment in SEGMENTS:
                if segment.road_type != "ARTERIAL":
                    continue
                for minute in range(7 * 60, 9 * 60, 10):
                    instant = datetime(jour.year, jour.month, jour.day, minute // 60, minute % 60, tzinfo=UTC)
                    if CAMPAGNE.label_state(segment, instant) == CONGESTED:
                        charge[segment.approach] += 1
        self.assertGreater(charge["N"] + charge["W"], charge["E"] + charge["S"])

    def test_un_incident_sature_son_troncon_et_ralentit_ses_voisins(self):
        for i in range(120):
            jour = LUNDI + timedelta(days=i)
            plan = day_plan(jour)
            if not plan.incidents:
                continue
            incident = plan.incidents[0]
            milieu = datetime(jour.year, jour.month, jour.day, tzinfo=UTC) + timedelta(seconds=incident.start_s + incident.duration_s // 2)
            segment = next(s for s in SEGMENTS if s.road_segment_id == incident.road_segment_id)
            self.assertEqual(CAMPAGNE.label_state(segment, milieu), CONGESTED)
            voisins = [s for s in SEGMENTS if s.intersection_id == segment.intersection_id and s is not segment]
            for voisin in voisins:
                self.assertIn(CAMPAGNE.label_state(voisin, milieu), (SLOW, CONGESTED))
            return
        self.fail("aucun incident sur 120 jours")


class Mesures(unittest.TestCase):
    def test_la_demande_suit_la_charge_du_jour_les_comptages_aussi(self):
        """Mêmes capteur et heure, deux jours : la demande est celle du jour (semaine contre week-end)."""
        segment = SEGMENTS[0]
        lundi = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
        samedi = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
        self.assertGreater(CAMPAGNE.demand_at(segment, lundi), CAMPAGNE.demand_at(segment, samedi))
        moyenne = lambda instant: statistics.mean(model.read(s, CAMPAGNE, segment, instant + timedelta(seconds=10 * k)).vehicle_count for s in range(1, 6) for k in range(12))
        self.assertGreater(moyenne(lundi), moyenne(samedi))

    def test_les_trois_scenarios_d_origine_donnent_les_memes_demandes_qu_avant(self):
        instant = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
        from novaria_sim.scenarios import demand_factor

        for nom in ("journee-calme", "heure-de-pointe", "incident-ponctuel"):
            for segment in SEGMENTS:
                self.assertEqual(SCENARIOS[nom].demand_at(segment, instant), SCENARIOS[nom].demand_scale * demand_factor(segment.road_type, 8 * 3600), nom)


class Run(unittest.TestCase):
    def test_un_run_de_la_campagne_est_rejoue_a_l_identique(self):
        premier = [d.event for d in play(config(CAMPAIGN_ID, minutes=3))[0]]
        second = [d.event for d in play(config(CAMPAIGN_ID, minutes=3))[0]]
        self.assertEqual(premier, second)
        self.assertGreater(len(premier), 0)

    def test_la_verite_terrain_n_est_jamais_dans_un_message(self):
        for delivery in play(config(CAMPAIGN_ID, minutes=2))[0]:
            self.assertNotIn("CONGESTED", str(delivery.event))


if __name__ == "__main__":
    unittest.main()
