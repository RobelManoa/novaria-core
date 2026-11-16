import unittest
from pathlib import Path

from streaming import sql

FICHIER = Path(__file__).resolve().parents[1] / "sql" / "agregats.sql"
VALEURS = {
    "KAFKA_SERVEURS": "kafka:9092",
    "SUJET": "iot.raw",
    "GROUPE": "g",
    "MONGO_URI": "mongodb://u:p@mongo:27017/novaria?authSource=novaria",
    "MONGO_BASE": "novaria",
    "MONGO_COLLECTION": "stream_window_aggregates",
}


class Rendu(unittest.TestCase):
    def test_le_fichier_du_job_a_exactement_les_six_jetons_attendus(self):
        self.assertEqual(sql.jetons_du_fichier(sql.lire(FICHIER)), set(VALEURS))

    def test_le_fichier_ne_contient_aucune_adresse_ni_secret_en_clair(self):
        texte = sql.lire(FICHIER)
        self.assertNotIn("mongodb://", texte)
        rendu = sql.rendre(texte, VALEURS)
        self.assertNotIn("{{", rendu)
        self.assertIn("mongodb://u:p@mongo", rendu)

    def test_un_jeton_sans_valeur_est_refuse(self):
        with self.assertRaisesRegex(sql.ErreurSql, "sans valeur"):
            sql.rendre("a {{X}} b {{Y}}", {"X": "1"})

    def test_une_valeur_sans_jeton_est_refusee(self):
        with self.assertRaisesRegex(sql.ErreurSql, "sans jeton"):
            sql.rendre("a {{X}}", {"X": "1", "Z": "2"})

    def test_une_valeur_qui_sortirait_de_la_chaine_est_refusee(self):
        for dangereuse in ("a'b", "a;b", "a\nb", "{{X}}", "a\\b", ""):
            with self.subTest(dangereuse=dangereuse), self.assertRaises(sql.ErreurSql):
                sql.rendre("x = '{{X}}'", {"X": dangereuse})

    def test_les_fenetres_et_le_retard_de_l_adr_011(self):
        texte = sql.lire(FICHIER)
        self.assertIn("INTERVAL '10' SECOND", texte)  # désordre admis
        self.assertIn("'table.exec.emit.allow-lateness' = '30 s'", texte)  # retard autorisé
        self.assertIn("TUMBLE(`time`, INTERVAL '1' MINUTE)", texte)
        self.assertIn("TUMBLE(`time`, INTERVAL '5' MINUTE)", texte)
        self.assertIn("PRIMARY KEY (road_segment_id, window_start, window_size_s, run_id)", texte)  # écriture idempotente


if __name__ == "__main__":
    unittest.main()
