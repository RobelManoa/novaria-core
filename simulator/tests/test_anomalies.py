"""Critère de MS-07 : chaque anomalie se déclenche à la demande, et ne touche que sa cible."""

import unittest
from datetime import UTC, datetime, timedelta

from helpers import START, config, digest, lines, play

from novaria_sim.anomalies import Anomaly, AnomalyError, parse_spec
from novaria_sim.events import to_line, utc_text
from novaria_sim.network import SEGMENT_BY_SENSOR
from novaria_sim.run import Run

BASE = None  # (messages, vérité terrain) du run sans anomalie, calculé une fois


def reference():
    global BASE
    if BASE is None:
        deliveries, truth, _ = play(config())
        BASE = ({d.event["id"]: to_line(d.event) for d in deliveries}, truth, lines(deliveries))
    return BASE


def at(seconds: int) -> datetime:
    return START + timedelta(seconds=seconds)


def event_id(sensor: str, seconds: int) -> str:
    return f"run-test:{sensor}:{int(at(seconds).timestamp() * 1000)}"


def with_anomalies(*specs):
    return play(config(anomalies=[parse_spec(spec, START) for spec in specs]))


def changed_ids(deliveries):
    """Identifiants dont le message diffère du run sans anomalie (ou qui n'y étaient pas)."""
    by_id, _, _ = reference()
    seen = {}
    for delivery in deliveries:
        seen.setdefault(delivery.event["id"], to_line(delivery.event))
    return {key for key, line in seen.items() if by_id.get(key) != line} | (set(by_id) - set(seen))


class Ecriture(unittest.TestCase):
    def test_en_ligne_de_commande_et_en_json(self):
        a = parse_spec("muet:sensor=SENSOR_007,at=+600,duration=5m", START)
        self.assertEqual((a.kind, a.sensor_id, a.start, a.intervals), ("muet", "SENSOR_007", at(600), 30))
        b = Anomaly.from_json({"kind": "retard", "sensor": "SENSOR_010", "at": "2026-10-20T07:35:00Z", "delay": 20})
        self.assertEqual((b.delay_s, b.start, b.intervals), (20, at(300), 1))

    def test_valeurs_par_defaut(self):
        self.assertEqual(parse_spec("muet:sensor=SENSOR_001,at=+10", START).intervals, 30)  # 5 minutes, plus de 60 s (DQ-08)
        self.assertEqual(parse_spec("retard:sensor=SENSOR_001,at=+10", START).delay_s, 45)  # plus de 30 s (DQ-04)
        self.assertEqual(parse_spec("aberrante:sensor=SENSOR_001,at=+10", START).variant, "vitesse")
        self.assertEqual(parse_spec("doublon:sensor=SENSOR_001,at=+10", START).copies, 1)

    def test_sans_date_l_anomalie_attend_le_prochain_intervalle(self):
        self.assertIsNone(parse_spec("doublon:sensor=SENSOR_001").start)

    def test_ecriture_relue_telle_quelle(self):
        for spec in ("aberrante:sensor=SENSOR_003,at=+30,variant=debit,duration=20s", "muet:sensor=SENSOR_007,at=+60,duration=2m",
                     "doublon:sensor=SENSOR_001,at=+20,copies=3,lag=7", "retard:sensor=SENSOR_010,at=+50,delay=33"):
            with self.subTest(spec=spec):
                original = parse_spec(spec, START)
                self.assertEqual(Anomaly.from_json(original.to_json()), original)

    def test_les_erreurs_disent_quoi_corriger(self):
        for spec, fragment in (
            ("inconnue:sensor=SENSOR_001", "type d'anomalie inconnu"),
            ("muet:at=+10", "sensor"),
            ("muet:sensor=SENSOR_999,at=+10", "capteur inconnu"),
            ("muet:sensor=SENSOR_001,at=+15", "multiple de 10"),
            ("muet:sensor=SENSOR_001,at=+10,duration=beaucoup", "durée illisible"),
            ("muet:sensor=SENSOR_001,at", "cle=valeur"),
            ("aberrante:sensor=SENSOR_001,at=+10,variant=jaune", "variante inconnue"),
            ("retard:sensor=SENSOR_001,at=+10,delay=0", "au moins 1 s"),
            ("doublon:sensor=SENSOR_001,at=+10,copies=11", "1 à 10 copies"),
            ("muet:sensor=SENSOR_001,at=2026-10-20T07:30:10", "sans fuseau"),
            ("muet:sensor=SENSOR_001,at=hier", "date illisible"),
            ("muet:sensor=SENSOR_001,at=+10,couleur=rouge", "champ inconnu"),
        ):
            with self.subTest(spec=spec), self.assertRaisesRegex(AnomalyError, fragment):
                parse_spec(spec, START)

    def test_une_anomalie_dans_le_passe_est_refusee(self):
        run = Run(config())
        run.step()
        with self.assertRaisesRegex(AnomalyError, "passé"):
            run.add_anomaly(parse_spec("muet:sensor=SENSOR_001,at=+10", START))


class Aberrante(unittest.TestCase):
    def cible(self, variant, sensor="SENSOR_003", extra=""):
        deliveries, truth, _ = with_anomalies(f"aberrante:sensor={sensor},at=+30,variant={variant}{extra}")
        message = next(d.event for d in deliveries if d.event["id"] == event_id(sensor, 30))
        return message["data"], deliveries, truth

    def test_vitesse_depasse_une_fois_et_demie_la_vitesse_fluide(self):
        for sensor, limite in (("SENSOR_003", 50), ("SENSOR_020", 30)):
            data, _, _ = self.cible("vitesse", sensor)
            self.assertGreater(data["average_speed_kmh"], 1.5 * limite)
            self.assertLessEqual(data["average_speed_kmh"], 200)
            self.assertEqual(data["quality"], {"status": "SUSPECT", "flags": ["IMPLAUSIBLE_VALUE"]})

    def test_une_vitesse_aberrante_survit_a_un_intervalle_sans_vehicule(self):
        # SENSOR_020 (voie locale) est vide à cette heure : sans véhicule, la vitesse devrait être nulle et l'anomalie disparaîtrait.
        sans_anomalie = next(d.event for d in play(config())[0] if d.event["id"] == event_id("SENSOR_020", 30))
        self.assertEqual(sans_anomalie["data"]["vehicle_count"], 0)
        data, _, _ = self.cible("vitesse", "SENSOR_020")
        self.assertGreaterEqual(data["vehicle_count"], 1)
        self.assertGreater(data["average_speed_kmh"], 45)

    def test_debit_depasse_40_vehicules_par_minute_et_par_voie(self):
        for sensor in ("SENSOR_003", "SENSOR_020"):  # deux voies, puis une voie
            data, _, _ = self.cible("debit", sensor)
            lanes = SEGMENT_BY_SENSOR[sensor].lane_count
            self.assertGreater(data["vehicle_count"] * 6 / lanes, 40)
            self.assertEqual(data["quality"]["status"], "SUSPECT")
            self.assertTrue(0 <= data["occupancy_rate"] <= 1)

    def test_vitesse_nulle_alors_que_des_vehicules_sont_passes(self):
        data, _, _ = self.cible("vitesse-nulle")
        self.assertGreaterEqual(data["vehicle_count"], 1)
        self.assertEqual(data["average_speed_kmh"], 0.0)
        self.assertEqual(data["quality"], {"status": "SUSPECT", "flags": ["IMPLAUSIBLE_VALUE"]})

    def test_plusieurs_intervalles_de_suite(self):
        _, deliveries, truth = self.cible("vitesse", extra=",duration=30s")
        suspects = [d.event["time"] for d in deliveries if d.event["data"]["sensor_id"] == "SENSOR_003" and d.event["data"]["quality"]["status"] == "SUSPECT"]
        self.assertEqual(suspects, [utc_text(at(s)) for s in (30, 40, 50)])

    def test_la_verite_terrain_note_l_anomalie_et_garde_l_etat_voulu(self):
        _, _, truth = self.cible("vitesse")
        marquees = [r for r in truth if r["anomalies"]]
        self.assertEqual([(r["event_id"], r["anomalies"]) for r in marquees], [(event_id("SENSOR_003", 30), ["OUTLIER"])])
        self.assertIn(marquees[0]["label_state"], ("FREE_FLOW", "SLOW", "CONGESTED"))

    def test_rien_d_autre_ne_change(self):
        for variant in ("vitesse", "debit", "vitesse-nulle"):
            _, deliveries, _ = self.cible(variant)
            with self.subTest(variant=variant):
                self.assertEqual(changed_ids(deliveries), {event_id("SENSOR_003", 30)})


class Muet(unittest.TestCase):
    def setUp(self):
        self.deliveries, self.truth, _ = with_anomalies("muet:sensor=SENSOR_007,at=+60,duration=40s")  # 4 intervalles : +60 à +90

    def test_le_capteur_n_envoie_rien_pendant_le_silence(self):
        temps = {d.event["time"] for d in self.deliveries if d.event["data"]["sensor_id"] == "SENSOR_007"}
        for seconds in (60, 70, 80, 90):
            self.assertNotIn(utc_text(at(seconds)), temps)
        for seconds in (50, 100):
            self.assertIn(utc_text(at(seconds)), temps)
        self.assertEqual(len(self.deliveries), 24 * 60 - 4)

    def test_le_premier_message_apres_le_silence_signale_le_trou(self):
        apres = next(d.event for d in self.deliveries if d.event["id"] == event_id("SENSOR_007", 100))
        self.assertEqual(apres["data"]["quality"], {"status": "VALID", "flags": ["GAP_BEFORE"]})
        suivant = next(d.event for d in self.deliveries if d.event["id"] == event_id("SENSOR_007", 110))
        self.assertEqual(suivant["data"]["quality"], {"status": "VALID"})

    def test_la_verite_terrain_garde_la_trace_des_messages_manquants(self):
        manquants = [r for r in self.truth if not r["emitted"]]
        self.assertEqual([r["event_id"] for r in manquants], [event_id("SENSOR_007", s) for s in (60, 70, 80, 90)])
        self.assertTrue(all(r["anomalies"] == ["SILENT"] and r["emit_at"] is None for r in manquants))
        self.assertEqual(len(self.truth), 24 * 60)  # une ligne par capteur et par intervalle, même muet

    def test_rien_d_autre_ne_change_que_le_silence_et_le_message_qui_le_suit(self):
        attendus = {event_id("SENSOR_007", s) for s in (60, 70, 80, 90, 100)}
        self.assertEqual(changed_ids(self.deliveries), attendus)

    def test_le_silence_par_defaut_depasse_les_60_s_de_la_regle_dq_08(self):
        deliveries, _, _ = with_anomalies("muet:sensor=SENSOR_007,at=+60")
        self.assertEqual(len(deliveries), 24 * 60 - 30)  # 5 minutes

    def test_un_silence_jusqu_a_la_fin_du_run(self):
        deliveries, truth, _ = with_anomalies("muet:sensor=SENSOR_007,at=+580,duration=10m")
        self.assertEqual(len([d for d in deliveries if d.event["data"]["sensor_id"] == "SENSOR_007"]), 57)
        self.assertEqual(len([r for r in truth if not r["emitted"]]), 3)


class Doublon(unittest.TestCase):
    def test_le_meme_message_arrive_plusieurs_fois_a_la_suite(self):
        deliveries, truth, _ = with_anomalies("doublon:sensor=SENSOR_001,at=+20,copies=2")
        sortie = lines(deliveries)
        cible = event_id("SENSOR_001", 20)
        position = [i for i, d in enumerate(deliveries) if d.event["id"] == cible]
        self.assertEqual(len(position), 3)
        self.assertEqual(position, list(range(position[0], position[0] + 3)))  # côte à côte
        self.assertEqual(len({sortie[i] for i in position}), 1)  # octet pour octet
        self.assertEqual(len(deliveries), 24 * 60 + 2)
        self.assertEqual(len({d.event["id"] for d in deliveries}), 24 * 60)  # même nombre d'identifiants distincts
        self.assertEqual([r["anomalies"] for r in truth if r["event_id"] == cible], [["DUPLICATE"]])

    def test_une_copie_peut_arriver_plus_tard(self):
        deliveries, _, _ = with_anomalies("doublon:sensor=SENSOR_001,at=+20,lag=25")
        cible = event_id("SENSOR_001", 20)
        position = [i for i, d in enumerate(deliveries) if d.event["id"] == cible]
        entre = [d.event["time"] for d in deliveries[position[0] + 1:position[1]]]
        self.assertTrue(entre)
        self.assertTrue(all(temps >= utc_text(at(20)) for temps in entre))  # les autres capteurs du même instant, puis les suivants
        self.assertTrue(any(temps > utc_text(at(20)) for temps in entre))  # la copie arrive après des messages plus récents
        self.assertEqual(deliveries[position[1]].emit_at - deliveries[position[0]].emit_at, timedelta(seconds=25))

    def test_rien_d_autre_ne_change(self):
        deliveries, _, _ = with_anomalies("doublon:sensor=SENSOR_001,at=+20,copies=2")
        self.assertEqual(changed_ids(deliveries), set())  # mêmes messages, simplement répétés


class Retard(unittest.TestCase):
    def test_le_message_arrive_apres_ceux_des_intervalles_suivants_sans_changer_son_instant(self):
        deliveries, truth, _ = with_anomalies("retard:sensor=SENSOR_010,at=+50,delay=45")
        cible = event_id("SENSOR_010", 50)
        index = next(i for i, d in enumerate(deliveries) if d.event["id"] == cible)
        self.assertEqual(deliveries[index].event["time"], utc_text(at(50)))  # l'instant d'événement ne bouge pas
        self.assertEqual(deliveries[index].emit_at, at(95))
        avant = [d.event["time"] for d in deliveries[:index]]
        apres = [d.event["time"] for d in deliveries[index + 1:]]
        self.assertIn(utc_text(at(90)), avant)  # les messages jusqu'à +90 sont déjà arrivés
        self.assertNotIn(utc_text(at(100)), avant)  # ceux de +100 arrivent après le message en retard
        self.assertIn(utc_text(at(100)), apres)
        self.assertEqual(len(deliveries), 24 * 60)  # rien n'est perdu
        ligne = next(r for r in truth if r["event_id"] == cible)
        self.assertEqual((ligne["anomalies"], ligne["emit_at"]), (["LATE"], utc_text(at(95))))

    def test_le_retard_par_defaut_depasse_les_30_s_autorises(self):
        deliveries, _, _ = with_anomalies("retard:sensor=SENSOR_010,at=+50")
        cible = next(d for d in deliveries if d.event["id"] == event_id("SENSOR_010", 50))
        self.assertGreater((cible.emit_at - at(50)).total_seconds(), 30)

    def test_un_retard_dans_la_tolerance(self):
        deliveries, _, _ = with_anomalies("retard:sensor=SENSOR_010,at=+50,delay=15")
        cible = next(d for d in deliveries if d.event["id"] == event_id("SENSOR_010", 50))
        self.assertEqual((cible.emit_at - at(50)).total_seconds(), 15)

    def test_le_simulateur_ne_pose_pas_le_drapeau_late(self):
        # C'est la collecte qui juge du retard à la réception (DQ-04) : le message garde sa qualité d'origine.
        deliveries, _, _ = with_anomalies("retard:sensor=SENSOR_010,at=+50,delay=45")
        cible = next(d.event for d in deliveries if d.event["id"] == event_id("SENSOR_010", 50))
        self.assertEqual(cible["data"]["quality"], {"status": "VALID"})

    def test_le_contenu_du_message_ne_change_pas_seul_l_ordre_de_livraison(self):
        deliveries, _, _ = with_anomalies("retard:sensor=SENSOR_010,at=+50,delay=45")
        self.assertEqual(changed_ids(deliveries), set())
        self.assertNotEqual(lines(deliveries), reference()[2])  # mais l'ordre, lui, a changé
        self.assertEqual(sorted(lines(deliveries)), sorted(reference()[2]))

    def test_un_message_en_retard_apres_la_fin_du_run_est_quand_meme_livre(self):
        deliveries, _, _ = with_anomalies("retard:sensor=SENSOR_010,at=+590,delay=120")
        self.assertEqual(len(deliveries), 24 * 60)
        self.assertEqual(deliveries[-1].event["id"], event_id("SENSOR_010", 590))

    def test_un_retard_et_un_doublon_ensemble_retardent_aussi_les_copies(self):
        deliveries, _, _ = with_anomalies("retard:sensor=SENSOR_010,at=+50,delay=45", "doublon:sensor=SENSOR_010,at=+50")
        cible = event_id("SENSOR_010", 50)
        reçus = [d for d in deliveries if d.event["id"] == cible]
        self.assertEqual([d.emit_at for d in reçus], [at(95), at(95)])


class ADemande(unittest.TestCase):
    """Injection pendant l'exécution : « maintenant » veut dire « au prochain intervalle »."""

    def jouer(self, injections):
        """`injections` : {numéro d'intervalle déjà traité: spec} ; rend (messages, run)."""
        run = Run(config())
        deliveries = []
        while not run.done:
            if run.processed in injections:
                run.add_anomaly(parse_spec(injections[run.processed]))
            deliveries += run.step().deliveries
        deliveries += run.finish()
        return deliveries, run

    def test_chaque_type_se_declenche_au_prochain_intervalle(self):
        for spec, verifier in (
            ("aberrante:sensor=SENSOR_003", lambda d: self.assertEqual(self.message(d, "SENSOR_003", 70)["data"]["quality"]["status"], "SUSPECT")),
            ("muet:sensor=SENSOR_003,duration=20s", lambda d: self.assertIsNone(self.message(d, "SENSOR_003", 70))),
            ("doublon:sensor=SENSOR_003", lambda d: self.assertEqual(sum(x.event["id"] == event_id("SENSOR_003", 70) for x in d), 2)),
            ("retard:sensor=SENSOR_003", lambda d: self.assertGreater([x.event["id"] for x in d].index(event_id("SENSOR_003", 70)), 24 * 7 + 3)),
        ):
            with self.subTest(spec=spec):
                deliveries, run = self.jouer({6: spec})  # six intervalles traités : le prochain se termine à +70 s
                verifier(deliveries)
                self.assertEqual(run.anomalies[0].start, at(70))

    def message(self, deliveries, sensor, seconds):
        return next((d.event for d in deliveries if d.event["id"] == event_id(sensor, seconds)), None)

    def test_le_passe_n_est_pas_modifie(self):
        deliveries, _ = self.jouer({6: "aberrante:sensor=SENSOR_003"})
        avant = [to_line(d.event) for d in deliveries if d.event["time"] <= utc_text(at(60))]
        self.assertEqual(avant, reference()[2][:len(avant)])

    def test_rien_d_autre_ne_change(self):
        deliveries, _ = self.jouer({6: "aberrante:sensor=SENSOR_003"})
        self.assertEqual(changed_ids(deliveries), {event_id("SENSOR_003", 70)})

    def test_plusieurs_injections_dans_un_meme_run(self):
        deliveries, run = self.jouer({6: "aberrante:sensor=SENSOR_003", 10: "muet:sensor=SENSOR_007,duration=30s"})
        self.assertEqual(len(run.anomalies), 2)
        self.assertEqual(changed_ids(deliveries), {event_id("SENSOR_003", 70), *(event_id("SENSOR_007", s) for s in (110, 120, 130, 140))})

    def test_un_run_avec_injection_se_rejoue_a_l_identique_depuis_ses_anomalies(self):
        deliveries, run = self.jouer({6: "aberrante:sensor=SENSOR_003,variant=debit", 10: "doublon:sensor=SENSOR_001,copies=2"})
        enregistrees = [a.to_json() for a in run.anomalies]  # ce que le manifeste garde
        rejoue, _, _ = play(config(anomalies=[Anomaly.from_json(a) for a in enregistrees]))
        self.assertEqual(digest(lines(rejoue)), digest(lines(deliveries)))


if __name__ == "__main__":
    unittest.main()
