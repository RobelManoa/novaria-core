"""Reprises limitées (ADR-019) : seule une indisponibilité passagère de l'API est rejouée, puis la dernière erreur est relevée."""

import tempfile
import unittest
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from tests.donnees import FausseApi

from rapport import api, chaine

ENV = {"NOVARIA_RPA_USER": "robot", "NOVARIA_RPA_PASSWORD": "secret-de-test-12", "NOVARIA_RPA_ATTENTE_S": "10"}
MAINTENANT = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)


class Reglage(unittest.TestCase):
    def test_valeurs_par_defaut(self):
        self.assertEqual(chaine.reglage_des_reprises({}), (3, 60.0))

    def test_valeurs_choisies(self):
        self.assertEqual(chaine.reglage_des_reprises({"NOVARIA_RPA_TENTATIVES": "5", "NOVARIA_RPA_ATTENTE_S": "0"}), (5, 0.0))

    def test_les_valeurs_hors_bornes_ou_illisibles_sont_refusees(self):
        for env in ({"NOVARIA_RPA_TENTATIVES": "0"}, {"NOVARIA_RPA_TENTATIVES": "11"}, {"NOVARIA_RPA_TENTATIVES": "beaucoup"},
                    {"NOVARIA_RPA_ATTENTE_S": "-1"}, {"NOVARIA_RPA_ATTENTE_S": "3601"}):
            with self.subTest(env=env), self.assertRaises(chaine.IdentifiantsAbsents):
                chaine.reglage_des_reprises(env)


class ErreursTransitoires(unittest.TestCase):
    def test_reseau_et_statuts_d_indisponibilite_sont_transitoires(self):
        for statut in (429, 502, 503, 504):
            with self.subTest(statut=statut), self.assertRaises(api.ErreurApi) as e:
                api._json(statut, b"{}", "lecture")
            self.assertTrue(e.exception.transitoire)

    def test_un_refus_ne_l_est_jamais(self):
        for statut in (400, 401, 403, 404, 422, 500):
            with self.subTest(statut=statut), self.assertRaises(api.ErreurApi) as e:
                api._json(statut, b'{"code": "X"}', "lecture")
            self.assertFalse(e.exception.transitoire)

    def test_une_api_injoignable_est_transitoire(self):
        requete = urllib.request.Request("http://127.0.0.1:9/")  # port fermé
        with self.assertRaises(api.ErreurApi) as e:
            api._envoyer(requete)
        self.assertTrue(e.exception.transitoire)


class AvecReprises(unittest.TestCase):
    def setUp(self):
        self.pauses, self.messages = [], []

    def action_qui_echoue(self, fois, transitoire=True):
        etat = {"appels": 0}

        def action():
            etat["appels"] += 1
            if etat["appels"] <= fois:
                raise api.ErreurApi(f"échec {etat['appels']}", transitoire=transitoire)
            return "ok"

        action.etat = etat
        return action

    def lancer(self, action, env=None):
        return chaine.avec_reprises(action, environnement={"NOVARIA_RPA_ATTENTE_S": "10", **(env or {})}, dormir=self.pauses.append,
                                    signaler=self.messages.append)

    def test_un_succes_ne_dort_pas(self):
        action = self.action_qui_echoue(0)
        self.assertEqual(self.lancer(action), "ok")
        self.assertEqual((action.etat["appels"], self.pauses), (1, []))

    def test_une_indisponibilite_passagere_est_rejouee_avec_une_attente_qui_double(self):
        action = self.action_qui_echoue(2)
        self.assertEqual(self.lancer(action), "ok")
        self.assertEqual((action.etat["appels"], self.pauses), (3, [10.0, 20.0]))
        self.assertEqual(len(self.messages), 2)
        self.assertIn("tentative 1/3", self.messages[0])

    def test_apres_la_derniere_tentative_la_derniere_erreur_est_relevee(self):
        action = self.action_qui_echoue(99)
        with self.assertRaises(api.ErreurApi) as e:
            self.lancer(action)
        self.assertEqual(str(e.exception), "échec 3")
        self.assertEqual((action.etat["appels"], self.pauses), (3, [10.0, 20.0]))

    def test_un_refus_n_est_jamais_rejoue(self):
        action = self.action_qui_echoue(99, transitoire=False)
        with self.assertRaises(api.ErreurApi):
            self.lancer(action)
        self.assertEqual((action.etat["appels"], self.pauses), (1, []))

    def test_le_nombre_de_tentatives_est_borne_par_le_reglage(self):
        action = self.action_qui_echoue(99)
        with self.assertRaises(api.ErreurApi):
            self.lancer(action, {"NOVARIA_RPA_TENTATIVES": "1"})
        self.assertEqual(action.etat["appels"], 1)
        action = self.action_qui_echoue(99)
        with self.assertRaises(api.ErreurApi):
            self.lancer(action, {"NOVARIA_RPA_TENTATIVES": "5"})
        self.assertEqual((action.etat["appels"], self.pauses[-4:]), (5, [10.0, 20.0, 40.0, 80.0]))

    def test_une_autre_exception_n_est_pas_avalee(self):
        def action():
            raise ValueError("bug")

        with self.assertRaises(ValueError):
            self.lancer(action)
        self.assertEqual(self.pauses, [])


class Chaine(unittest.TestCase):
    """La chaîne entière : une API qui redémarre au moment du rapport n'empêche pas le rapport."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name) / "rapports"

    def produire(self, envoyer, pauses):
        return chaine.produire("http://127.0.0.1:8000", self.dossier, debut="2026-10-19", maintenant=MAINTENANT, envoyer=envoyer,
                               environnement=ENV, dormir=pauses.append)

    def api_qui_redemarre(self, fois, statut=503):
        vraie, etat = FausseApi(), {"appels": 0}

        def envoyer(requete):
            etat["appels"] += 1
            if etat["appels"] <= fois:
                return statut, b'{"code": "UPSTREAM_UNAVAILABLE"}'
            return vraie(requete)

        envoyer.etat = etat
        return envoyer

    def test_une_api_qui_redemarre_deux_fois_donne_quand_meme_le_rapport(self):
        pauses = []
        resultat = self.produire(self.api_qui_redemarre(2), pauses)
        self.assertTrue(resultat.chemin_pdf.is_file())
        self.assertEqual(pauses, [10.0, 20.0])

    def test_une_api_toujours_indisponible_echoue_apres_trois_tentatives_sans_rien_deposer(self):
        pauses = []
        envoyer = self.api_qui_redemarre(99)
        with self.assertRaises(api.ErreurApi) as e:
            self.produire(envoyer, pauses)
        self.assertIn("503", str(e.exception))
        self.assertEqual(envoyer.etat["appels"], 3)
        self.assertFalse(self.dossier.exists() and list(self.dossier.glob("*.pdf")))

    def test_un_mot_de_passe_refuse_echoue_tout_de_suite(self):
        pauses = []
        envoyer = self.api_qui_redemarre(99, statut=401)
        with self.assertRaises(api.ErreurApi):
            self.produire(envoyer, pauses)
        self.assertEqual((envoyer.etat["appels"], pauses), (1, []))


if __name__ == "__main__":
    unittest.main()
