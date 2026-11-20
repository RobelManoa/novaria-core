import unittest

from streaming import mongo, recalcul, verifier

from .donnees import mesure


def document(agregat: recalcul.Agregat, **changements) -> dict:
    """Le document tel que Flink l'écrit : clé primaire dans `_id`, dates en JSON étendu de mongosh."""
    corps = {
        "_id": {
            "road_segment_id": agregat.road_segment_id,
            "window_start": {"$date": recalcul.iso(agregat.window_start)},
            "window_size_s": agregat.window_size_s,
            "run_id": agregat.run_id,
        },
        "window_end": {"$date": recalcul.iso(agregat.window_end)},
        "intersection_id": agregat.intersection_id,
        "source_type": agregat.source_type,
        "sample_count": agregat.sample_count,
        "vehicle_count": agregat.vehicle_count,
        "flow_veh_per_min": agregat.flow_veh_per_min,
        "average_speed_kmh": agregat.average_speed_kmh,
        "occupancy_rate": agregat.occupancy_rate,
        "max_queue_length_m": agregat.max_queue_length_m,
        "non_valid_count": agregat.non_valid_count,
        "window_size_s": agregat.window_size_s,
    }
    corps.update(changements)
    return corps


class Comparaison(unittest.TestCase):
    def setUp(self):
        self.messages = [mesure(f"2026-10-20T08:0{minute}:{seconde:02d}Z") for minute in range(0, 3) for seconde in (10, 30, 50)]
        self.attendus = recalcul.agreger(self.messages, (60,))
        self.fermees = recalcul.fenetres_fermees(self.attendus, recalcul.secondes("2026-10-20T08:02:00Z"))

    def documents(self):
        return [document(agregat) for cle, agregat in self.fermees.items()]

    def test_des_documents_egaux_au_recalcul_sont_conformes(self):
        rapport = verifier.comparer(self.documents(), self.attendus, self.fermees)
        self.assertTrue(rapport.conforme, rapport)
        self.assertEqual((rapport.attendus, rapport.egales, rapport.ouvertes), (2, 2, 1))

    def test_un_compteur_different_est_un_ecart(self):
        documents = self.documents()
        documents[0]["sample_count"] = documents[0]["sample_count"] - 1
        rapport = verifier.comparer(documents, self.attendus, self.fermees)
        self.assertFalse(rapport.conforme)
        self.assertIn("sample_count", rapport.ecarts[0])

    def test_une_valeur_reelle_dans_l_arrondi_est_acceptee_au_dela_non(self):
        documents = self.documents()
        documents[0]["average_speed_kmh"] += 0.001
        self.assertTrue(verifier.comparer(documents, self.attendus, self.fermees).conforme)
        documents[0]["average_speed_kmh"] += 0.5
        self.assertFalse(verifier.comparer(documents, self.attendus, self.fermees).conforme)

    def test_une_fenetre_fermee_absente_est_manquante(self):
        rapport = verifier.comparer(self.documents()[:1], self.attendus, self.fermees)
        self.assertEqual(len(rapport.manquantes), 1)
        self.assertFalse(rapport.conforme)

    def test_une_fenetre_inconnue_du_recalcul_est_en_trop(self):
        etrangere = recalcul.agreger([mesure("2026-10-20T09:00:10Z")], (60,))
        documents = self.documents() + [document(next(iter(etrangere.values())))]
        rapport = verifier.comparer(documents, self.attendus, self.fermees)
        self.assertEqual(len(rapport.en_trop), 1)

    def test_une_fenetre_ouverte_deja_ecrite_n_est_pas_en_trop(self):
        # Flink peut écrire une fenêtre avant que le filigrane de fin d'essai ne la ferme (ex. mise à jour tardive) : elle existe au recalcul.
        ouverte = next(a for cle, a in self.attendus.items() if cle not in self.fermees)
        rapport = verifier.comparer(self.documents() + [document(ouverte)], self.attendus, self.fermees)
        self.assertEqual(rapport.en_trop, [])

    def test_valeurs_absentes_comparees_comme_telles(self):
        agregat = recalcul.agreger([mesure("2026-10-20T08:00:10Z", vehicules=0, vitesse=None)], (60,))
        cle, valeur = next(iter(agregat.items()))
        self.assertTrue(verifier.comparer([document(valeur)], agregat, agregat).conforme)
        self.assertFalse(verifier.comparer([document(valeur, average_speed_kmh=12.0)], agregat, agregat).conforme)

    def test_la_cle_se_lit_dans_l_id_ou_a_plat(self):
        agregat = next(iter(self.attendus.values()))
        dans_id = document(agregat)
        a_plat = {**dans_id, **dans_id["_id"], "_id": "autre"}
        self.assertEqual(verifier.cle_du_document(dans_id), verifier.cle_du_document(a_plat))
        self.assertEqual(verifier.cle_du_document(dans_id), agregat.cle)


class LectureMongo(unittest.TestCase):
    def test_la_ligne_documents_est_lue(self):
        self.assertEqual(mongo.lire_documents('bruit\nDOCUMENTS=[{"a": 1}]\n'), [{"a": 1}])

    def test_sans_ligne_documents_la_lecture_echoue(self):
        with self.assertRaises(ValueError):
            mongo.lire_documents("rien\n")

    def test_le_script_de_preparation_ne_contient_aucun_secret_et_limite_les_droits(self):
        self.assertNotIn("change-me", mongo.SCRIPT_PREPARATION)
        self.assertIn("process.env." + mongo.VARIABLE_MOT_DE_PASSE, mongo.SCRIPT_PREPARATION)
        self.assertIn('actions: ["find", "insert", "update"]', mongo.SCRIPT_PREPARATION)
        self.assertNotIn("remove", mongo.SCRIPT_PREPARATION.replace("removeprefix", ""))


if __name__ == "__main__":
    unittest.main()
