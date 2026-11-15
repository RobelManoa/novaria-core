import json
import unittest
from unittest import mock

from tests.donnees import FausseApi, jeu

from rapport import api

BASE = "http://127.0.0.1:8000"


class Connexion(unittest.TestCase):
    def test_un_jeton_est_rendu_et_le_corps_porte_les_identifiants(self):
        fausse = FausseApi()
        self.assertEqual(api.se_connecter(BASE, "robot", "secret-de-test-12", fausse), "jeton-opaque")
        methode, url, _, corps = fausse.appels[0]
        self.assertEqual((methode, url), ("POST", f"{BASE}/api/v1/auth/login"))
        self.assertEqual(json.loads(corps), {"username": "robot", "password": "secret-de-test-12"})

    def test_un_refus_dit_le_code_sans_jamais_citer_le_mot_de_passe(self):
        with self.assertRaises(api.ErreurApi) as contexte:
            api.se_connecter(BASE, "robot", "mauvais-mot-de-passe", FausseApi())
        self.assertIn("401", str(contexte.exception))
        self.assertIn("INVALID_CREDENTIALS", str(contexte.exception))
        self.assertNotIn("mauvais-mot-de-passe", str(contexte.exception))

    def test_une_reponse_sans_jeton_est_refusee(self):
        with self.assertRaises(api.ErreurApi):
            api.se_connecter(BASE, "r", "p", lambda _: (200, b'{"token_type": "bearer"}'))

    def test_une_adresse_qui_n_est_pas_http_est_refusee_avant_tout_appel(self):
        fausse = FausseApi()
        for base in ("ftp://hote", "file:///etc/passwd", "127.0.0.1:8000", "http://"):
            with self.subTest(base=base), self.assertRaises(api.ErreurApi):
                api.se_connecter(base, "r", "p", fausse)
        self.assertEqual(fausse.appels, [])

    def test_une_api_injoignable_est_une_erreur_claire(self):
        import urllib.error

        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refusé")):
            with self.assertRaises(api.ErreurApi) as contexte:
                api.se_connecter(BASE, "r", "p")
        self.assertIn("injoignable", str(contexte.exception))


class Lecture(unittest.TestCase):
    def test_toutes_les_pages_sont_lues_avec_le_curseur(self):
        fausse = FausseApi(jeu(3, 12), taille_page=10)
        donnees = api.lire_indicateurs(BASE, "jeton-opaque", "2026-10-19T00:00:00Z", "2026-10-26T00:00:00Z", envoyer=fausse)
        self.assertEqual((len(donnees.lignes), donnees.tronque), (36, False))
        self.assertEqual(len(fausse.appels), 4)

    def test_la_requete_porte_la_periode_la_fenetre_et_le_jeton_et_ne_fait_que_lire(self):
        fausse = FausseApi()
        api.lire_indicateurs(BASE, "jeton-opaque", "2026-10-19T00:00:00Z", "2026-10-26T00:00:00Z", envoyer=fausse)
        methode, url, entetes, _ = fausse.appels[0]
        self.assertEqual(methode, "GET")
        for attendu in ("from=2026-10-19T00%3A00%3A00Z", "to=2026-10-26T00%3A00%3A00Z", "window_size_s=300", "limit=500"):
            self.assertIn(attendu, url)
        self.assertEqual(entetes["Authorization"], "Bearer jeton-opaque")

    def test_le_plafond_de_pages_arrete_la_lecture_et_le_dit(self):
        fausse = FausseApi(jeu(3, 12), taille_page=5)
        with mock.patch.object(api, "MAX_PAGES", 3):
            donnees = api.lire_indicateurs(BASE, "jeton-opaque", "a", "b", envoyer=fausse)
        self.assertEqual((len(donnees.lignes), donnees.tronque), (15, True))

    def test_un_jeton_refuse_est_une_erreur_sans_le_jeton(self):
        with self.assertRaises(api.ErreurApi) as contexte:
            api.lire_indicateurs(BASE, "autre-jeton", "a", "b", envoyer=FausseApi())
        self.assertIn("UNAUTHENTICATED", str(contexte.exception))
        self.assertNotIn("autre-jeton", str(contexte.exception))

    def test_une_periode_vide_donne_une_liste_vide(self):
        donnees = api.lire_indicateurs(BASE, "jeton-opaque", "a", "b", envoyer=FausseApi([]))
        self.assertEqual((donnees.lignes, donnees.tronque), ([], False))


if __name__ == "__main__":
    unittest.main()
