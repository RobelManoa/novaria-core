"""Le parcours de bout en bout (CLD-13) : ses calculs, ses jetons et son orchestration, sans Docker ni réseau.

Ce qui exige la pile (collecte, flux, entrepôt, API, navigateur) se joue avec `dev.py parcours` ; ici on vérifie que
le banc de preuve ne ment pas : valeurs attendues recalculées à la main, jeton construit comme celui de l'API, un cas
précédent en échec qui rend les suivants « non joués », compte jetable supprimé même après un échec.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_parcours.py"  (Windows : py -3 ...).
"""

import base64
import json
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import parcours as p

try:
    import jwt
except ImportError:  # PyJWT n'est pas dans la bibliothèque standard : le test croisé est ignoré sans lui
    jwt = None

MAINTENANT = datetime(2026, 11, 17, 12, 57, 31, tzinfo=UTC)
SECRET = "s" * 40


class MesuresEtValeursAttendues(unittest.TestCase):
    def setUp(self):
        self.debut = p.debut_de_minute_passee(MAINTENANT)
        self.mesures = p.minute_nominale("cld13-test", self.debut)

    def test_la_minute_choisie_est_entiere_alignee_et_terminee_depuis_plus_de_deux_minutes(self):
        self.assertEqual(self.debut, datetime(2026, 11, 17, 12, 55, tzinfo=UTC))
        self.assertEqual(self.debut.second, 0)
        self.assertGreaterEqual((MAINTENANT - (self.debut + timedelta(seconds=60))).total_seconds(), 30)

    def test_six_mesures_couvrent_la_minute_et_aucune_n_est_dans_le_futur(self):
        self.assertEqual(len(self.mesures), 6)
        fins = [m["time"] for m in self.mesures]
        self.assertEqual(fins[0], "2026-11-17T12:55:10Z")
        self.assertEqual(fins[-1], "2026-11-17T12:56:00Z")
        self.assertTrue(all(datetime.fromisoformat(f.replace("Z", "+00:00")) < MAINTENANT for f in fins))

    def test_l_identifiant_porte_l_instant_a_la_seconde_pres_comme_le_contrat_l_exige(self):
        for m in self.mesures:
            instant = int(datetime.fromisoformat(m["time"].replace("Z", "+00:00")).timestamp()) * 1000
            self.assertEqual(m["id"], f"cld13-test:SENSOR_001:{instant}")

    def test_une_fin_avec_des_microsecondes_garde_un_identifiant_coherent(self):
        fin = datetime(2026, 11, 17, 12, 55, 10, 761000, tzinfo=UTC)
        m = p.mesure("r", fin, 1, 30.0, 0.2, 1.0)
        self.assertTrue(m["id"].endswith(":1794920110000"))
        self.assertEqual(m["time"], "2026-11-17T12:55:10Z")

    def test_les_valeurs_attendues_sont_celles_d_un_calcul_a_la_main(self):
        # 4+6+5+3+7+5 = 30 véhicules ; (126 + 168 + 152,5 + 99 + 206,5 + 150) / 30 = 30,0667 ; moyenne des occupations 0,24
        attendu = p.indicateur_attendu(self.mesures)
        self.assertEqual(attendu, {
            "vehicle_count": "30", "flow_veh_per_min": "30.00", "average_speed_kmh": "30.1", "occupancy_rate": "0.240",
            "max_queue_length_m": "22.0", "sample_count": "6", "expected_sample_count": "6",
        })

    def test_l_arrondi_est_moitie_vers_le_haut_pas_au_pair(self):
        self.assertEqual(p.arrondir(Decimal("0.3125"), 3), Decimal("0.313"))
        self.assertEqual(p.arrondir(Decimal("38.25"), 1), Decimal("38.3"))

    def test_les_ecarts_nomment_chaque_champ_qui_differe_et_ignorent_les_ecritures_equivalentes(self):
        attendu = {"vehicle_count": "30", "average_speed_kmh": "30.1"}
        self.assertEqual(p.ecarts(attendu, {"vehicle_count": 30, "average_speed_kmh": "30.10"}), [])
        self.assertEqual(p.ecarts(attendu, {"vehicle_count": 29, "average_speed_kmh": "30.1"}), ["vehicle_count : attendu 30, lu 29"])
        self.assertEqual(len(p.ecarts(attendu, {})), 2)


class Affichage(unittest.TestCase):
    def test_l_ecran_ecrit_a_la_francaise(self):
        self.assertEqual(p.francais("16171.5"), "16 171,5")
        self.assertEqual(p.francais("30"), "30")
        self.assertEqual(p.nombre_affiche("30.00", 1), "30,0")
        self.assertEqual(p.nombre_affiche("30.0667", 1), "30,1")
        self.assertEqual(p.nombre_affiche("30", 0), "30")


class Jetons(unittest.TestCase):
    def charge(self, valeur: str) -> dict:
        morceau = valeur.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(morceau + "=" * (-len(morceau) % 4)))

    def test_les_revendications_sont_celles_de_l_api(self):
        valeur = p.jeton(SECRET, "u-1", "viewer", MAINTENANT + timedelta(minutes=5))
        charge = self.charge(valeur)
        self.assertEqual(set(charge), {"sub", "role", "iat", "exp"})
        self.assertEqual(charge["exp"] - charge["iat"], 1800)
        self.assertEqual(charge["sub"], "u-1")

    def test_un_jeton_expire_a_une_date_passee(self):
        valeur = p.jeton(SECRET, "u-1", "viewer", MAINTENANT - timedelta(minutes=1))
        self.assertLess(self.charge(valeur)["exp"], MAINTENANT.timestamp())

    def test_la_signature_alteree_garde_la_charge_et_change_la_signature(self):
        valeur = p.jeton(SECRET, "u-1", "viewer", MAINTENANT)
        alteree = p.mal_signe(valeur)
        self.assertNotEqual(alteree, valeur)
        self.assertEqual(alteree.rsplit(".", 1)[0], valeur.rsplit(".", 1)[0])
        self.assertNotEqual(p.mal_signe(valeur[:-1] + "A"), valeur[:-1] + "A")

    @unittest.skipIf(jwt is None, "PyJWT absent : pip install pyjwt")
    def test_la_bibliotheque_de_l_api_lit_le_jeton_valide_et_refuse_les_deux_autres(self):
        valide = p.jeton(SECRET, "u-1", "viewer", datetime.now(UTC) + timedelta(minutes=5))
        self.assertEqual(jwt.decode(valide, SECRET, algorithms=["HS256"])["role"], "viewer")
        with self.assertRaises(jwt.ExpiredSignatureError):
            jwt.decode(p.jeton(SECRET, "u-1", "viewer", datetime.now(UTC) - timedelta(minutes=1)), SECRET, algorithms=["HS256"])
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(p.mal_signe(valide), SECRET, algorithms=["HS256"])


class PileFausse:
    """Remplace la pile : aucun appel réseau, la suppression du compte est enregistrée."""

    def __init__(self):
        self.supprimes = []
        self.racine = None

    def supprimer_compte(self, nom):
        self.supprimes.append(nom)


def reussir(contexte):
    return "fait"


def echouer(contexte):
    raise p.Echec("preuve manquante")


def planter(contexte):
    raise KeyError("champ")


def nommer(contexte):
    contexte.nom = "parcours-abc"
    return "compte"


class Orchestration(unittest.TestCase):
    def jouer(self, cas, ids=None):
        original = p.CAS
        p.CAS = cas
        try:
            pile = PileFausse()
            return pile, p.executer(pile, ids, maintenant=MAINTENANT)
        finally:
            p.CAS = original

    def test_un_echec_du_nominal_rend_les_etapes_suivantes_non_jouees_mais_pas_les_cas_d_echec(self):
        _, resultats = self.jouer((("N1", "a", reussir), ("N2", "b", echouer), ("N3", "c", reussir), ("E1", "d", reussir)))
        self.assertEqual([r.ok for r in resultats], [True, False, False, True])
        self.assertIn("non joué", resultats[2].preuve)
        self.assertEqual(resultats[1].preuve, "preuve manquante")

    def test_une_exception_inattendue_est_un_echec_du_cas_et_la_suite_est_jouee(self):
        _, resultats = self.jouer((("E1", "a", planter), ("E2", "b", reussir)))
        self.assertFalse(resultats[0].ok)
        self.assertIn("KeyError", resultats[0].preuve)
        self.assertTrue(resultats[1].ok)

    def test_le_compte_jetable_est_supprime_meme_apres_un_echec(self):
        pile, resultats = self.jouer((("N1", "a", nommer), ("N2", "b", echouer)))
        self.assertEqual(pile.supprimes, ["parcours-abc"])
        self.assertFalse(resultats[1].ok)

    def test_on_peut_ne_jouer_que_certains_cas(self):
        _, resultats = self.jouer((("N1", "a", reussir), ("E1", "b", reussir), ("E2", "c", reussir)), ids=("E2",))
        self.assertEqual([r.cas for r in resultats], ["E2"])

    def test_la_ligne_du_compte_rendu_dit_le_verdict_sans_secret(self):
        self.assertEqual(p.ligne(p.Resultat("N1", "Compte", True, "ok")), "[OK] N1  Compte : ok")
        self.assertTrue(p.ligne(p.Resultat("E3", "Base", False, "x")).startswith("[ÉCHEC] E3"))

    def test_les_neuf_cas_du_critere_sont_la(self):
        self.assertEqual([cas[0] for cas in p.CAS], ["N1", "N2", "N3", "N4", "N5", "N6", "E1", "E2", "E3"])


if __name__ == "__main__":
    unittest.main()
