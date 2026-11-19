"""Planificateur hebdomadaire : créneaux, rattrapage d'un rapport manquant, attente par petits pas, horaires refusés."""

import tempfile
import unittest
from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

from rapport import depot, periode, planificateur

MAURICE = timezone(timedelta(hours=4))
KIRITIMATI = timezone(timedelta(hours=14))
SEPT_HEURES = time(7, 0)


def instant(texte: str, fuseau=MAURICE) -> datetime:
    return datetime.fromisoformat(texte).replace(tzinfo=fuseau)


class Saisies(unittest.TestCase):
    def test_heure_valide(self):
        self.assertEqual(planificateur.lire_heure("07:00"), time(7, 0))
        self.assertEqual(planificateur.lire_heure("23:59"), time(23, 59))

    def test_heure_invalide(self):
        for texte in ("7h", "24:00", "07:60", "", "07:00:00", "ab:cd"):
            with self.subTest(texte=texte), self.assertRaises(planificateur.HoraireInvalide):
                planificateur.lire_heure(texte)

    def test_jours(self):
        self.assertEqual([planificateur.lire_jour(j) for j in ("lundi", "Dimanche", " mercredi ")], [0, 6, 2])
        with self.assertRaises(planificateur.HoraireInvalide):
            planificateur.lire_jour("monday")


class Creneaux(unittest.TestCase):
    def prochain(self, maintenant, jour=0, heure=SEPT_HEURES):
        return planificateur.prochain_creneau(maintenant, jour, heure, MAURICE)

    def test_jeudi_le_prochain_lundi(self):
        self.assertEqual(self.prochain(instant("2026-11-12 17:33")), instant("2026-11-16 07:00"))

    def test_lundi_avant_l_heure_c_est_le_jour_meme(self):
        self.assertEqual(self.prochain(instant("2026-11-16 06:59")), instant("2026-11-16 07:00"))

    def test_lundi_a_l_heure_pile_ou_apres_c_est_la_semaine_suivante(self):
        self.assertEqual(self.prochain(instant("2026-11-16 07:00")), instant("2026-11-23 07:00"))
        self.assertEqual(self.prochain(instant("2026-11-16 12:00")), instant("2026-11-23 07:00"))

    def test_dimanche_soir_le_lendemain(self):
        self.assertEqual(self.prochain(instant("2026-11-15 23:59")), instant("2026-11-16 07:00"))

    def test_un_instant_en_utc_est_ramene_a_l_heure_du_poste(self):
        self.assertEqual(self.prochain(datetime(2026, 11, 16, 2, 59, tzinfo=UTC)), instant("2026-11-16 07:00"))  # 06:59 à Maurice
        self.assertEqual(self.prochain(datetime(2026, 11, 16, 3, 0, tzinfo=UTC)), instant("2026-11-23 07:00"))

    def test_un_autre_jour(self):
        self.assertEqual(self.prochain(instant("2026-11-12 17:33"), jour=4, heure=time(18, 30)), instant("2026-11-13 18:30"))

    def test_le_creneau_est_toujours_apres_maintenant(self):
        maintenant = instant("2026-11-16 07:00")
        for _ in range(30):
            creneau = self.prochain(maintenant)
            self.assertGreater(creneau, maintenant)
            self.assertEqual((creneau.weekday(), creneau.hour, creneau.minute), (0, 7, 0))
            maintenant = creneau

    def test_l_heure_d_ete_est_celle_du_jour_vise(self):
        """Avec le fuseau du poste, le créneau garde 07:00 locales de part et d'autre d'un changement d'heure."""
        import os
        import time as horloge

        ancien = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Paris"
        horloge.tzset()
        try:
            avant = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)  # vendredi, avant le passage à l'heure d'été (dimanche 29 mars)
            creneau = planificateur.prochain_creneau(avant, 0, SEPT_HEURES)  # lundi 30 mars, heure d'été
            self.assertEqual((creneau.hour, creneau.minute), (7, 0))
            self.assertEqual(creneau.astimezone(UTC).hour, 5)  # 07:00 à UTC+2
        finally:
            if ancien is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = ancien
            horloge.tzset()


class Horaires(unittest.TestCase):
    def test_lundi_sept_heures_a_maurice_est_accepte(self):
        planificateur.verifier_le_creneau(instant("2026-11-16 07:00"))

    def test_lundi_matin_a_un_fuseau_tres_en_avance_est_refuse(self):
        """Lundi 07:00 à UTC+14 est encore dimanche en UTC : la semaine à rapporter n'est pas finie."""
        with self.assertRaises(planificateur.HoraireInvalide) as e:
            planificateur.verifier_le_creneau(instant("2026-11-16 07:00", KIRITIMATI))
        self.assertIn("dimanche", str(e.exception).lower())

    def test_la_limite_est_lundi_zero_heure_utc(self):
        planificateur.verifier_le_creneau(instant("2026-11-16 14:00", KIRITIMATI))  # lundi 00:00 UTC pile
        with self.assertRaises(planificateur.HoraireInvalide):
            planificateur.verifier_le_creneau(instant("2026-11-16 13:59", KIRITIMATI))

    def test_un_fuseau_en_retard_est_toujours_accepte(self):
        planificateur.verifier_le_creneau(instant("2026-11-16 07:00", timezone(timedelta(hours=-8))))

    def test_un_autre_jour_n_est_pas_concerne(self):
        planificateur.verifier_le_creneau(instant("2026-11-17 07:00", KIRITIMATI))  # mardi 17:00 UTC lundi : même semaine ISO


class Rattrapage(unittest.TestCase):
    MAINTENANT = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)  # lundi de la semaine 44

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name)

    def deposer(self, quand: datetime):
        p = periode.choisir(None, None, quand)
        depot.deposer(self.dossier, p, "t", b"%PDF-1.4\n", quand)

    def test_sans_rapport_de_la_semaine_precedente_il_faut_le_produire(self):
        self.assertTrue(planificateur.rapport_a_rattraper(self.dossier, self.MAINTENANT))

    def test_avec_le_rapport_de_la_semaine_precedente_rien_a_faire(self):
        self.deposer(self.MAINTENANT)
        self.assertFalse(planificateur.rapport_a_rattraper(self.dossier, self.MAINTENANT))

    def test_le_rapport_d_une_autre_semaine_ne_compte_pas(self):
        self.deposer(self.MAINTENANT - timedelta(days=7))
        self.assertTrue(planificateur.rapport_a_rattraper(self.dossier, self.MAINTENANT))

    def test_des_metadonnees_sans_rapport_ne_comptent_pas_et_un_pdf_seul_non_plus(self):
        p = periode.choisir(None, None, self.MAINTENANT)
        (self.dossier / f"{depot.identifiant(p)}.pdf").write_bytes(b"x")  # le PDF est écrit d'abord, les métadonnées en dernier
        self.assertTrue(planificateur.rapport_a_rattraper(self.dossier, self.MAINTENANT))


class Horloge:
    """Une horloge simulée : `dormir` avance le temps, sans attendre."""

    def __init__(self, debut: datetime):
        self.t = debut
        self.pauses: list[float] = []

    def maintenant(self) -> datetime:
        return self.t

    def dormir(self, secondes: float) -> None:
        self.pauses.append(secondes)
        self.t += timedelta(seconds=secondes)


class Boucle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name)
        self.lancements: list[tuple[list[str], datetime]] = []
        self.journal: list[str] = []

    def lancer_avec(self, horloge, code=0):
        def lancer(commande):
            self.lancements.append((commande, horloge.t))
            return code

        return lancer

    def boucle(self, horloge, **options):
        return planificateur.boucle(0, SEPT_HEURES, ["rpa", "report"], self.dossier, maintenant=horloge.maintenant, dormir=horloge.dormir,
                                    lancer=self.lancer_avec(horloge, options.pop("code", 0)), journal=self.journal.append, fuseau=MAURICE, **options)

    def test_attend_le_creneau_puis_lance_la_commande(self):
        horloge = Horloge(instant("2026-11-12 17:33"))
        self.boucle(horloge, rattrapage=False, executions=1)
        (commande, quand), = self.lancements
        self.assertEqual(commande, ["rpa", "report"])
        self.assertEqual(quand, instant("2026-11-16 07:00"))
        self.assertTrue(all(0 <= p <= planificateur.PAS_DE_VEILLE_S for p in horloge.pauses), "l'attente se fait par petits pas")
        self.assertGreater(len(horloge.pauses), 100)

    def test_lance_chaque_semaine(self):
        horloge = Horloge(instant("2026-11-12 17:33"))
        self.boucle(horloge, rattrapage=False, executions=3)
        self.assertEqual([quand for _, quand in self.lancements], [instant("2026-11-16 07:00"), instant("2026-11-23 07:00"), instant("2026-11-30 07:00")])

    def test_le_rattrapage_lance_tout_de_suite_si_le_rapport_manque(self):
        horloge = Horloge(instant("2026-11-12 17:33"))
        self.boucle(horloge, rattrapage=True, executions=2)
        self.assertEqual(self.lancements[0][1], instant("2026-11-12 17:33"))
        self.assertEqual(self.lancements[1][1], instant("2026-11-16 07:00"))
        self.assertTrue(any("rattrapage" in ligne for ligne in self.journal))

    def test_pas_de_rattrapage_si_le_rapport_est_deja_la(self):
        maintenant = instant("2026-11-12 17:33")
        p = periode.choisir(None, None, maintenant.astimezone(UTC))
        depot.deposer(self.dossier, p, "t", b"%PDF-1.4\n", maintenant)
        horloge = Horloge(maintenant)
        self.boucle(horloge, rattrapage=True, executions=1)
        self.assertEqual(self.lancements[0][1], instant("2026-11-16 07:00"))

    def test_un_echec_de_la_commande_est_journalise_et_la_boucle_continue(self):
        horloge = Horloge(instant("2026-11-12 17:33"))
        self.boucle(horloge, rattrapage=False, executions=2, code=1)
        self.assertEqual(len(self.lancements), 2)
        self.assertEqual(sum("code de sortie 1" in ligne for ligne in self.journal), 2)

    def test_le_journal_annonce_le_prochain_lancement(self):
        horloge = Horloge(instant("2026-11-12 17:33"))
        self.boucle(horloge, rattrapage=False, executions=1)
        self.assertTrue(any("prochain lancement" in ligne and "lundi 16/11/2026 à 07:00" in ligne for ligne in self.journal))

    def test_un_creneau_impossible_arrete_la_boucle(self):
        horloge = Horloge(instant("2026-11-12 17:33", KIRITIMATI))
        with self.assertRaises(planificateur.HoraireInvalide):
            planificateur.boucle(0, SEPT_HEURES, ["x"], self.dossier, rattrapage=False, maintenant=horloge.maintenant, dormir=horloge.dormir,
                                 lancer=lambda c: 0, journal=self.journal.append, executions=1, fuseau=KIRITIMATI)
        self.assertEqual(self.lancements, [])


class LigneDeCommande(unittest.TestCase):
    def test_sans_commande_apres_les_deux_tirets_c_est_refuse(self):
        self.assertEqual(planificateur.main(["--jour", "lundi"]), 2)

    def test_horaire_invalide_refuse(self):
        self.assertEqual(planificateur.main(["--heure", "25:00", "--", "x"]), 2)
        self.assertEqual(planificateur.main(["--jour", "jour", "--", "x"]), 2)

    def test_les_options_arrivent_a_la_boucle(self):
        with mock.patch.object(planificateur, "boucle", return_value=0) as boucle:
            code = planificateur.main(["--jour", "mardi", "--heure", "08:15", "--dossier", "d", "--sans-rattrapage", "--executions", "2", "--", "a", "--b"])
        self.assertEqual(code, 0)
        args, options = boucle.call_args
        self.assertEqual((args[0], args[1], args[2], args[3]), (1, time(8, 15), ["a", "--b"], Path("d")))
        self.assertEqual((options["rattrapage"], options["executions"]), (False, 2))

    def test_ctrl_c_arrete_proprement(self):
        with mock.patch.object(planificateur, "boucle", side_effect=KeyboardInterrupt):
            self.assertEqual(planificateur.main(["--", "x"]), 0)


if __name__ == "__main__":
    unittest.main()
