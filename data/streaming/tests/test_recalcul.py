import unittest

from streaming import recalcul

from .donnees import mesure


class Arrondi(unittest.TestCase):
    def test_moitie_vers_le_haut_comme_flink(self):
        self.assertEqual(recalcul.arrondi(0.0005), 0.001)
        self.assertEqual(recalcul.arrondi(2.0005), 2.001)
        self.assertEqual(recalcul.arrondi(1.2344), 1.234)

    def test_absent_reste_absent(self):
        self.assertIsNone(recalcul.arrondi(None))


class Fenetres(unittest.TestCase):
    def test_une_fenetre_d_une_minute_regroupe_ses_mesures_debut_inclus_fin_exclue(self):
        messages = [mesure(f"2026-10-20T08:00:{s:02d}Z") for s in range(10, 60, 10)] + [mesure("2026-10-20T08:01:00Z")]
        agregats = recalcul.agreger(messages, (60,))
        premiere = agregats[("ROAD_001", recalcul.secondes("2026-10-20T08:00:00Z"), 60, "run-t")]
        self.assertEqual(premiere.sample_count, 5)  # 08:00:10 à 08:00:50 ; 08:01:00 ouvre la fenêtre suivante
        self.assertEqual(len(agregats), 2)

    def test_les_deux_tailles_sont_calculees(self):
        agregats = recalcul.agreger([mesure("2026-10-20T08:00:10Z")])
        self.assertEqual({cle[2] for cle in agregats}, {60, 300})

    def test_les_troncons_et_les_executions_ne_se_melangent_pas(self):
        messages = [
            mesure("2026-10-20T08:00:10Z", troncon="ROAD_001"),
            mesure("2026-10-20T08:00:10Z", troncon="ROAD_002", identifiant="b"),
            mesure("2026-10-20T08:00:10Z", run="run-autre", identifiant="c"),
        ]
        self.assertEqual(len(recalcul.agreger(messages, (60,))), 3)


class Valeurs(unittest.TestCase):
    def un_agregat(self, messages):
        return next(iter(recalcul.agreger(messages, (60,)).values()))

    def test_vitesse_ponderee_par_les_vehicules(self):
        agregat = self.un_agregat([mesure("2026-10-20T08:00:10Z", vehicules=1, vitesse=10.0), mesure("2026-10-20T08:00:20Z", vehicules=3, vitesse=50.0)])
        self.assertEqual(agregat.average_speed_kmh, 40.0)  # (1x10 + 3x50) / 4 ; la moyenne simple vaudrait 30
        self.assertEqual(agregat.vehicle_count, 4)
        self.assertEqual(agregat.flow_veh_per_min, 4.0)

    def test_sans_vehicule_la_vitesse_est_absente(self):
        agregat = self.un_agregat([mesure("2026-10-20T08:00:10Z", vehicules=0, vitesse=None)])
        self.assertIsNone(agregat.average_speed_kmh)
        self.assertEqual(agregat.vehicle_count, 0)

    def test_une_mesure_sans_vitesse_ne_pese_pas_au_denominateur(self):
        agregat = self.un_agregat([mesure("2026-10-20T08:00:10Z", vehicules=2, vitesse=30.0), mesure("2026-10-20T08:00:20Z", vehicules=8, vitesse=None)])
        self.assertEqual(agregat.average_speed_kmh, 30.0)
        self.assertEqual(agregat.vehicle_count, 10)

    def test_qualite_file_et_occupation(self):
        agregat = self.un_agregat([
            mesure("2026-10-20T08:00:10Z", qualite="SUSPECT", file=5.0, occupation=0.2),
            mesure("2026-10-20T08:00:20Z", file=30.0, occupation=0.4),
            mesure("2026-10-20T08:00:30Z", qualite="PARTIAL", file=None, occupation=None),
        ])
        self.assertEqual(agregat.non_valid_count, 2)
        self.assertEqual(agregat.max_queue_length_m, 30.0)
        self.assertEqual(agregat.occupancy_rate, 0.3)

    def test_un_doublon_est_compte_une_fois(self):
        message = mesure("2026-10-20T08:00:10Z")
        self.assertEqual(self.un_agregat([message, dict(message)]).sample_count, 1)

    def test_un_message_en_retard_compte_dans_la_reference(self):
        # La référence ne perd rien : c'est ce qui permet de voir ce que le flux a écarté.
        messages = [mesure("2026-10-20T08:01:30Z"), mesure("2026-10-20T08:00:10Z")]
        self.assertEqual(len(recalcul.agreger(messages, (60,))), 2)


class Filigrane(unittest.TestCase):
    def test_filigrane_et_fenetres_fermees(self):
        messages = [mesure("2026-10-20T08:00:10Z"), mesure("2026-10-20T08:01:20Z")]
        filigrane = recalcul.instant_du_filigrane(messages)
        self.assertEqual(filigrane, recalcul.secondes("2026-10-20T08:01:10Z"))
        fermees = recalcul.fenetres_fermees(recalcul.agreger(messages, (60,)), filigrane)
        self.assertEqual([recalcul.iso(cle[1]) for cle in fermees], ["2026-10-20T08:00:00Z"])  # la fenêtre de 08:01 finit à 08:02

    def test_instant_sans_fuseau_refuse(self):
        with self.assertRaises(ValueError):
            recalcul.secondes("2026-10-20T08:00:10")


if __name__ == "__main__":
    unittest.main()
