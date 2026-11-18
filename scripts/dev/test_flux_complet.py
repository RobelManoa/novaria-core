"""Le flux complet (MS-15) : ses mesures, ses valeurs attendues et son orchestration, sans pile ni Docker.

Ce qui exige la pile (collecte, Kafka, flux, pipeline, alerte, feux) se joue avec `dev.py flux-complet` ; ici on vérifie que le banc de
preuve ne ment pas : mesures conformes au contrat, valeurs attendues recalculées à la main, un cas qui échoue rend le suivant « non joué »,
le compte jetable est supprimé même après un échec, un service arrêté est attendu de nouveau avant le cas suivant.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_flux_complet.py"  (Windows : py -3 ...).
"""

import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import flux_complet as fc
import parcours

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "simulator"))

try:
    sys.path.insert(0, str(RACINE / "contracts"))
    import validate_events
except ImportError:  # jsonschema et referencing ne sont pas dans la bibliothèque standard : le test croisé est ignoré sans eux
    validate_events = None

MAINTENANT = datetime(2026, 11, 18, 13, 30, 45, tzinfo=UTC)


class Mesures(unittest.TestCase):
    def test_les_capteurs_sont_ceux_du_reseau_v0(self):
        from novaria_sim import network

        for numero in range(1, 7):
            attendus = [(s.approach, s.sensor_id, s.road_segment_id) for s in network.SEGMENTS if s.intersection_id == f"INT_{numero:02d}"]
            self.assertEqual(fc.capteurs(numero), attendus)

    def test_un_run_a_six_mesures_par_minute_et_par_capteur_dans_l_ordre_du_temps(self):
        debut = datetime(2026, 11, 18, 13, 0, tzinfo=UTC)
        mesures = fc.mesures_du_run("ms15-t", 2, debut, (True, False, True))
        self.assertEqual(len(mesures), 3 * 6 * 4)
        instants = [m["time"] for m in mesures]
        self.assertEqual(instants, sorted(instants))
        self.assertEqual(instants[0], "2026-11-18T13:00:10Z")
        self.assertEqual(instants[-1], "2026-11-18T13:03:00Z")
        self.assertEqual(len({m["id"] for m in mesures}), len(mesures))
        self.assertEqual({m["data"]["intersection_id"] for m in mesures}, {"INT_02"})
        self.assertEqual({m["data"]["sensor_id"] for m in mesures}, {"SENSOR_005", "SENSOR_006", "SENSOR_007", "SENSOR_008"})

    def test_la_minute_congestionnee_est_lente_et_la_fluide_rapide(self):
        debut = datetime(2026, 11, 18, 13, 0, tzinfo=UTC)
        mesures = fc.mesures_du_run("ms15-t", 1, debut, (True, False))
        self.assertEqual({m["data"]["average_speed_kmh"] for m in mesures if m["time"] <= "2026-11-18T13:01:00Z"}, {9.0})
        self.assertEqual({m["data"]["average_speed_kmh"] for m in mesures if m["time"] > "2026-11-18T13:01:00Z"}, {45.0})

    def test_une_minute_de_plus_continue_apres_les_precedentes(self):
        debut = datetime(2026, 11, 18, 13, 0, tzinfo=UTC)
        suite = fc.mesures_du_run("ms15-t", 4, debut, (False, False), premiere_minute=4)
        self.assertEqual(suite[0]["time"], "2026-11-18T13:04:10Z")
        self.assertEqual(suite[-1]["time"], "2026-11-18T13:06:00Z")

    @unittest.skipIf(validate_events is None, "pip install jsonschema referencing")
    def test_chaque_mesure_respecte_le_contrat(self):
        debut = datetime(2026, 11, 18, 13, 0, tzinfo=UTC)
        for m in fc.mesures_du_run("ms15-t", 3, debut, (True, False)):
            self.assertEqual(validate_events.validate_event(m), [], m["id"])

    def test_le_debut_de_plage_laisse_au_moins_150_secondes_apres_la_derniere_minute(self):
        for minutes in (1, 4, 8, 12):
            debut = fc.debut_pour(minutes, MAINTENANT)
            fin = debut + timedelta(minutes=minutes)
            self.assertEqual(debut.second, 0)
            # la dernière mesure est au moins 90 s dans le passé et jamais dans le futur
            self.assertGreaterEqual((MAINTENANT - fin).total_seconds(), 90, (minutes, debut))


class ValeursAttendues(unittest.TestCase):
    def test_une_fenetre_congestionnee_vaut_18_vehicules_a_9_kmh(self):
        self.assertEqual(fc.fenetre_attendue(True), {"vehicle_count": 18.0, "average_speed_kmh": 9.0, "occupancy_rate": 0.7, "max_queue_length_m": 150.0, "sample_count": 6.0})
        self.assertEqual(fc.fenetre_attendue(False)["average_speed_kmh"], 45.0)
        self.assertEqual(fc.fenetre_attendue(False)["max_queue_length_m"], 0.0)

    def test_l_hysteresis_entre_au_deuxieme_pas_lent_et_sort_au_troisieme_pas_rapide(self):
        self.assertEqual(fc.etats_attendus(fc.PLAN_NOMINAL),
                         ["FREE_FLOW", "CONGESTED", "CONGESTED", "CONGESTED", "CONGESTED", "CONGESTED", "FREE_FLOW", "FREE_FLOW"])

    def _fenetres(self, plan, carrefour=1, etats=None):
        attendus = etats or fc.etats_attendus(plan)
        sortie = []
        for _, _, troncon in fc.capteurs(carrefour):
            for m, congestionnee in enumerate(plan):
                v = fc.fenetre_attendue(congestionnee)
                sortie.append({"troncon": troncon, "minute": f"2026-11-18 13:{m:02d}", "vehicle_count": str(int(v["vehicle_count"])),
                               "average_speed_kmh": str(v["average_speed_kmh"]), "occupancy_rate": str(v["occupancy_rate"]),
                               "max_queue_length_m": str(v["max_queue_length_m"]), "sample_count": "6", "etat": attendus[m]})
        return sortie

    def test_des_fenetres_conformes_ne_donnent_aucun_ecart(self):
        self.assertEqual(fc.verifier_fenetres(self._fenetres(fc.PLAN_NOMINAL), fc.PLAN_NOMINAL, 1), [])

    def test_un_ecart_de_valeur_un_etat_faux_ou_une_fenetre_manquante_sont_nommes(self):
        fenetres = self._fenetres(fc.PLAN_NOMINAL)
        fenetres[3]["vehicle_count"] = "17"
        fenetres[9]["etat"] = "FREE_FLOW"
        problemes = fc.verifier_fenetres(fenetres, fc.PLAN_NOMINAL, 1)
        self.assertTrue(any("vehicle_count = 17" in p for p in problemes), problemes)
        self.assertTrue(any("état FREE_FLOW" in p for p in problemes), problemes)
        manquantes = [f for f in fenetres if f["troncon"] != "ROAD_004"]
        self.assertTrue(any("ROAD_004 : 0 fenêtres" in p for p in fc.verifier_fenetres(manquantes, fc.PLAN_NOMINAL, 1)))


class Aides(unittest.TestCase):
    def test_attendre_rend_la_premiere_valeur_vraie(self):
        valeurs = iter([None, 0, "prêt"])
        with mock.patch.object(fc.time, "sleep"):
            self.assertEqual(fc.attendre(lambda: next(valeurs), 30, 1), "prêt")

    def test_attendre_leve_un_echec_qui_dit_ce_qui_manque(self):
        horloge = iter([0.0, 1.0, 5.0, 12.0])
        with mock.patch.object(fc.time, "sleep"), mock.patch.object(fc.time, "monotonic", side_effect=lambda: next(horloge)):
            with self.assertRaisesRegex(parcours.Echec, "rien de prêt .*après 10 s"):
                fc.attendre(lambda: None, 10, 1, "rien de prêt")

    def test_les_identifiants_de_run_sont_neufs_a_chaque_appel(self):
        self.assertNotEqual(fc.nouveau_run(), fc.nouveau_run())
        self.assertRegex(fc.nouveau_run(), r"^ms15-[0-9a-f]{6}$")

    def test_la_lecture_d_un_sujet_ignore_les_lignes_qui_ne_sont_pas_des_messages(self):
        pile = fc.Pile({})
        sortie = '[2026-11-18 13:00:00] WARN quelque chose\n{"id": "a", "data": {"x": 1}}\nProcessed a total of 1 messages\n{"id": "b"}\n'
        with mock.patch.object(pile, "docker", return_value=mock.Mock(stdout=sortie)) as docker:
            self.assertEqual(pile.sujet("signal.status"), [{"id": "a", "data": {"x": 1}}, {"id": "b"}])
        self.assertIn("--from-beginning", docker.call_args.args)

    def test_creer_un_compte_refuse_remonte_la_sortie(self):
        pile = fc.Pile({})
        with mock.patch.object(pile, "docker", return_value=mock.Mock(returncode=1, stdout="Erreur : identifiant déjà pris")):
            with self.assertRaisesRegex(parcours.Echec, "identifiant déjà pris"):
                pile.creer_compte_role("x", "y", "operator")

    def test_le_compte_est_cree_une_seule_fois(self):
        pile = mock.Mock()
        pile.connexion.return_value = "jeton"
        contexte = fc.Contexte(pile)
        fc.compte(contexte)
        fc.compte(contexte)
        pile.creer_compte_role.assert_called_once()
        self.assertEqual(pile.creer_compte_role.call_args.args[2], "operator")
        self.assertEqual(contexte.jeton, "jeton")

    def test_la_sante_demande_la_collecte_et_la_passerelle(self):
        pile = fc.Pile({})
        with mock.patch.object(pile, "appel", return_value=(200, {})) as appel:
            self.assertTrue(pile.sante())
        self.assertEqual(appel.call_count, 2)
        with mock.patch.object(pile, "appel", side_effect=[(200, {}), (503, {})]):
            self.assertFalse(pile.sante())


class PileFausse(fc.Pile):
    """Remplace la pile : aucun appel réseau, chaque suppression de compte est enregistrée."""

    def __init__(self, sante=True):
        super().__init__({})
        self.supprimes = []
        self.etat_sante = sante

    def sante(self):
        return self.etat_sante

    def supprimer_compte(self, nom):
        self.supprimes.append(nom)


def reussir(contexte):
    return "fait"


def echouer(contexte):
    raise parcours.Echec("preuve manquante")


def planter(contexte):
    raise KeyError("champ")


def nommer(contexte):
    contexte.nom = "ms15-abc"
    return "compte"


class Orchestration(unittest.TestCase):
    def jouer(self, cas, ids=None, pile=None):
        original = fc.CAS
        fc.CAS = cas
        try:
            pile = pile or PileFausse()
            return pile, fc.executer(pile, ids)
        finally:
            fc.CAS = original

    def test_un_echec_du_nominal_rend_les_etapes_suivantes_non_jouees_mais_pas_les_cas_d_echec(self):
        _, resultats = self.jouer((("N1", "a", reussir), ("N2", "b", echouer), ("N3", "c", reussir), ("F1", "d", reussir)))
        self.assertEqual([r.ok for r in resultats], [True, False, False, True])
        self.assertIn("non joué", resultats[2].preuve)
        self.assertEqual(resultats[1].preuve, "preuve manquante")

    def test_une_exception_inattendue_est_un_echec_du_cas_et_la_suite_est_jouee(self):
        _, resultats = self.jouer((("F1", "a", planter), ("F2", "b", reussir)))
        self.assertFalse(resultats[0].ok)
        self.assertIn("KeyError", resultats[0].preuve)
        self.assertTrue(resultats[1].ok)

    def test_f5_n_est_pas_joue_quand_f4_a_echoue(self):
        _, resultats = self.jouer((("F4", "a", echouer), ("F5", "b", reussir)))
        self.assertEqual([r.ok for r in resultats], [False, False])
        self.assertIn("F4 n'a pas réussi", resultats[1].preuve)

    def test_f5_est_joue_seul_quand_f4_n_est_pas_demande(self):
        _, resultats = self.jouer((("F4", "a", echouer), ("F5", "b", reussir)), ids=("F5",))
        self.assertEqual([(r.cas, r.ok) for r in resultats], [("F5", True)])

    def test_le_compte_jetable_est_supprime_meme_apres_un_echec(self):
        pile, resultats = self.jouer((("N1", "a", nommer), ("N2", "b", echouer)))
        self.assertEqual(pile.supprimes, ["ms15-abc"])
        self.assertFalse(resultats[1].ok)

    def test_un_cas_d_echec_qui_laisse_la_pile_muette_le_dit(self):
        pile = PileFausse()

        def arreter(contexte):
            pile.etat_sante = False
            return "service arrêté"

        with mock.patch.object(fc, "attendre_pile_prete", side_effect=[None, parcours.Echec("la collecte ne répond pas")]):
            _, resultats = self.jouer((("F2", "a", arreter),), pile=pile)
        self.assertFalse(resultats[0].ok)
        self.assertIn("la pile ne répond plus après le cas", resultats[0].preuve)

    def test_on_peut_ne_jouer_que_certains_cas(self):
        _, resultats = self.jouer((("N1", "a", reussir), ("F1", "b", reussir), ("F2", "c", reussir)), ids=("F2",))
        self.assertEqual([r.cas for r in resultats], ["F2"])

    def test_les_treize_cas_de_l_issue_sont_la(self):
        self.assertEqual([cas[0] for cas in fc.CAS], ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "F1", "F2", "F3", "F4", "F5", "F6"])

    def test_la_ligne_du_compte_rendu_dit_le_verdict(self):
        self.assertEqual(fc.ligne(parcours.Resultat("F3", "Broker", True, "503")), "[OK] F3  Broker : 503")


class CommandeDev(unittest.TestCase):
    def test_un_cas_inconnu_est_refuse_avant_toute_action(self):
        import dev

        with mock.patch.object(dev, "require_env"), mock.patch.object(dev, "require_docker"), mock.patch.object(fc, "executer") as executer, \
                mock.patch("sys.stderr") as erreur:
            self.assertEqual(dev.main(["flux-complet", "z9"]), 2)  # `main` transforme l'erreur en message et en code 2
        executer.assert_not_called()
        self.assertIn("Cas inconnu : Z9", "".join(c.args[0] for c in erreur.write.call_args_list))

    def test_les_cas_sont_transmis_en_majuscules(self):
        import dev

        with mock.patch.object(dev, "require_env"), mock.patch.object(dev, "require_docker"), \
                mock.patch.object(dev.ENV_FILE.__class__, "read_text", return_value="GATEWAY_PORT=8000\n"), \
                mock.patch.object(fc, "executer", return_value=[parcours.Resultat("F1", "x", True, "ok")]) as executer, mock.patch("builtins.print"):
            self.assertEqual(dev.main(["flux-complet", "f1"]), 0)
        self.assertEqual(executer.call_args.args[1], ("F1",))

    def test_un_cas_en_echec_donne_le_code_1(self):
        import dev

        with mock.patch.object(dev, "require_env"), mock.patch.object(dev, "require_docker"), \
                mock.patch.object(dev.ENV_FILE.__class__, "read_text", return_value="GATEWAY_PORT=8000\n"), \
                mock.patch.object(fc, "executer", return_value=[parcours.Resultat("F1", "x", False, "écart")]), mock.patch("builtins.print"):
            self.assertEqual(dev.main(["flux-complet", "f1"]), 1)


if __name__ == "__main__":
    unittest.main()
