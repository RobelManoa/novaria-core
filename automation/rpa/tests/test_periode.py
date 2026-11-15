import unittest
from datetime import UTC, date, datetime

from tests import donnees  # noqa: F401  (ajoute le paquet au chemin)

from rapport import periode


class Periode(unittest.TestCase):
    def test_une_semaine_va_du_lundi_inclus_au_lundi_suivant_exclu(self):
        semaine = periode.semaine_de(date(2026, 10, 22))  # jeudi
        self.assertEqual(semaine.debut, datetime(2026, 10, 19, tzinfo=UTC))
        self.assertEqual(semaine.fin, datetime(2026, 10, 26, tzinfo=UTC))
        self.assertEqual(semaine.etiquette, "2026-S43")
        self.assertEqual(semaine.libelle, "du 19/10/2026 au 25/10/2026")

    def test_le_lundi_et_le_dimanche_sont_dans_la_meme_semaine(self):
        self.assertEqual(periode.semaine_de(date(2026, 10, 19)), periode.semaine_de(date(2026, 10, 25)))

    def test_la_semaine_precedente_est_complete_quel_que_soit_le_jour_du_declenchement(self):
        for jour in (26, 27, 28, 29, 30, 31):
            with self.subTest(jour=jour):
                precedente = periode.semaine_precedente(datetime(2026, 10, jour, 0, 30, tzinfo=UTC))
                self.assertEqual(precedente.debut, datetime(2026, 10, 19, tzinfo=UTC))
                self.assertEqual(precedente.fin, datetime(2026, 10, 26, tzinfo=UTC))
        dimanche = periode.semaine_precedente(datetime(2026, 11, 1, 23, 59, tzinfo=UTC))
        self.assertEqual(dimanche.debut, datetime(2026, 10, 19, tzinfo=UTC))

    def test_le_passage_d_annee_suit_la_semaine_iso(self):
        self.assertEqual(periode.semaine_de(date(2027, 1, 1)).etiquette, "2026-S53")
        self.assertEqual(periode.semaine_de(date(2027, 1, 4)).etiquette, "2027-S01")

    def test_un_fuseau_est_ramene_en_utc(self):
        from datetime import timedelta, timezone

        tard = datetime(2026, 10, 25, 23, 30, tzinfo=timezone(timedelta(hours=-5)))  # lundi 26 04:30 UTC
        self.assertEqual(periode.semaine_precedente(tard).debut, datetime(2026, 10, 19, tzinfo=UTC))

    def test_sans_date_la_semaine_precedente_est_prise(self):
        self.assertEqual(
            periode.choisir(None, None, datetime(2026, 11, 3, tzinfo=UTC)).debut, datetime(2026, 10, 26, tzinfo=UTC)
        )

    def test_un_debut_seul_donne_sept_jours(self):
        choisie = periode.choisir("2026-10-19", None, datetime(2026, 11, 3, tzinfo=UTC))
        self.assertEqual((choisie.fin - choisie.debut).days, 7)

    def test_une_periode_explicite_est_validee(self):
        maintenant = datetime(2026, 11, 3, tzinfo=UTC)
        for debut, fin in [("19/10/2026", None), ("2026-10-19", "pas une date"), ("2026-10-26", "2026-10-19"),
                           ("2026-10-19", "2026-10-19"), ("2026-01-01", "2026-03-01"), (None, "2026-10-26"), ("", "2026-10-26")]:
            with self.subTest(debut=debut, fin=fin), self.assertRaises(periode.PeriodeInvalide):
                periode.choisir(debut, fin, maintenant)


if __name__ == "__main__":
    unittest.main()
