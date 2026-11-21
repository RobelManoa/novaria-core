"""Le parcours de l'usager (CIT-07) : l'enchaînement des cas, leurs vérifications et leurs nettoyages, sans Docker ni navigateur.

La pile, la base, l'API et Chromium sont remplacés par des faux : ces tests prouvent que chaque cas **sait échouer** (un état faux, un champ
interne en trop, une alerte absente, un statut refusé) et que les nettoyages (refermer les alertes, relancer le service) sont joués même après
un échec. Le vrai parcours se joue avec `dev.py parcours` (pile locale). Lancement : python3 -m unittest discover -s scripts/dev -p "test_parcours_usager.py".
"""

import json
import queue
import re
import subprocess
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import dev
import flux_complet as flux
import parcours
import parcours_usager as u

RACINE = Path(__file__).resolve().parents[2]
MAINTENANT = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
TRONCONS = ["ROAD_017", "ROAD_018", "ROAD_019", "ROAD_020"]
ATTENDUS = ["FREE_FLOW", "CONGESTED", "CONGESTED", "CONGESTED"]


class PileFausse:
    def __init__(self, statuts=None, etats=None, statut_indicateurs=200):
        self.statuts, self.etats, self.statut_indicateurs = statuts, etats, statut_indicateurs
        self.envois, self.supprimes, self.docker_appels = [], [], []
        self.passerelle, self.racine = "http://passerelle", RACINE

    def envoyer(self, mesures):
        self.envois.append(mesures)
        return self.statuts if self.statuts is not None else ["ACCEPTED"] * len(mesures)

    def indicateurs(self, run, jeton):
        etats = self.etats if self.etats is not None else {t: ATTENDUS for t in TRONCONS}
        items = [{"road_segment_id": t, "window_start": f"2026-11-21T14:5{m}:00Z", "congestion_state": e} for t, liste in etats.items() for m, e in enumerate(liste)]
        return self.statut_indicateurs, {"items": items}

    def supprimer_compte(self, nom):
        self.supprimes.append(nom)

    def docker(self, *args, **kwargs):
        self.docker_appels.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")


def contexte(pile=None, **notes):
    c = parcours.Contexte(pile or PileFausse(), "cit07-test", MAINTENANT)
    c.jeton = "jeton-d-essai"
    c.notes.update({"run": "cit07-test", "carrefour": 5, "debut": MAINTENANT, **notes})
    return c


def attendre_une_fois(condition, delai_s, pas_s=3.0, message="condition non atteinte"):
    valeur = condition()
    if not valeur:
        raise u.Echec(f"{message} (après {delai_s:g} s)")
    return valeur


class Enchainement(unittest.TestCase):
    def test_la_liste_complete_garde_l_ordre_nominal_usager_puis_echecs(self):
        self.assertEqual([c[0] for c in u.tous_les_cas()], ["N1", "N2", "N3", "N4", "N5", "N6", "U1", "U2", "U3", "U4", "U5", "E1", "E2", "E3"])
        self.assertEqual(len({c[0] for c in u.tous_les_cas()}), 14)

    def test_les_cas_de_l_usager_se_suivent_et_u5_depend_de_u1_a_u3_seulement(self):
        self.assertEqual(u.CHAINES[1], ("U1", "U2", "U3", "U4"))
        self.assertEqual(u.CHAINES[2], ("U1", "U2", "U3", "U5"))
        self.assertNotIn("U4", u.CHAINES[2], "un échec de l'affichage ne doit pas masquer l'essai de la panne")

    def jouer(self, resultats_par_cas):
        faux = tuple((i, i, (lambda c, i=i: self.rendre(resultats_par_cas[i]))) for i in resultats_par_cas)
        return parcours.executer(PileFausse(), None, maintenant=MAINTENANT, cas=faux, chaines=u.CHAINES)

    @staticmethod
    def rendre(ok):
        if not ok:
            raise u.Echec("raté")
        return "fait"

    def test_un_echec_de_u1_rend_u2_a_u5_non_joues_mais_pas_les_echecs(self):
        resultats = self.jouer({"U1": False, "U2": True, "U3": True, "U4": True, "U5": True, "E1": True})
        self.assertEqual([(r.cas, r.ok) for r in resultats], [("U1", False), ("U2", False), ("U3", False), ("U4", False), ("U5", False), ("E1", True)])
        self.assertTrue(all("non joué" in r.preuve for r in resultats[1:5]))

    def test_un_echec_de_u4_ne_supprime_pas_l_essai_de_la_panne_u5(self):
        resultats = {r.cas: r for r in self.jouer({"U1": True, "U2": True, "U3": True, "U4": False, "U5": True})}
        self.assertFalse(resultats["U4"].ok)
        self.assertTrue(resultats["U5"].ok, "U5 ne dépend pas de l'affichage")

    def test_un_echec_de_u3_rend_u4_et_u5_non_joues(self):
        resultats = {r.cas: r for r in self.jouer({"U1": True, "U2": True, "U3": False, "U4": True, "U5": True})}
        self.assertEqual((resultats["U4"].ok, resultats["U5"].ok), (False, False))

    def test_le_parcours_nominal_garde_sa_chaine(self):
        resultats = self.jouer({"N1": True, "N2": False, "N3": True, "U1": True})
        self.assertEqual([(r.cas, r.ok) for r in resultats], [("N1", True), ("N2", False), ("N3", False), ("U1", True)])

    def test_les_nettoyages_sont_joues_en_ordre_inverse_meme_apres_un_echec_et_un_nettoyage_rate_ne_masque_rien(self):
        ordre = []

        def enregistrer(c):
            c.nettoyages.append(lambda: ordre.append("refermer"))
            c.nettoyages.append(lambda: (_ for _ in ()).throw(RuntimeError("raté")))
            c.nettoyages.append(lambda: ordre.append("relancer"))
            raise u.Echec("raté après avoir enregistré")

        resultats = parcours.executer(PileFausse(), None, maintenant=MAINTENANT, cas=(("U1", "u", enregistrer),), chaines=u.CHAINES)
        self.assertFalse(resultats[0].ok)
        self.assertEqual(ordre, ["relancer", "refermer"])


class Mesures(unittest.TestCase):
    def jouer(self, pile):
        c = parcours.Contexte(pile, "cit07-test", MAINTENANT)
        with mock.patch.object(u.citoyen_delai, "choisir_carrefour", return_value=5), mock.patch.object(u.flux, "nouveau_run", return_value="cit07-abc"):
            return c, u.u1_mesures(c)

    def test_quatre_minutes_congestionnees_de_quatre_capteurs_sont_envoyees_et_acceptees(self):
        pile = PileFausse()
        c, texte = self.jouer(pile)
        self.assertEqual(len(pile.envois[0]), 4 * 4 * flux.MESURES_PAR_MINUTE)
        self.assertIn("96 mesures", texte)
        self.assertEqual((c.notes["run"], c.notes["carrefour"]), ("cit07-abc", 5))

    def test_le_nettoyage_envoie_des_minutes_fluides_apres_les_minutes_congestionnees(self):
        pile = PileFausse()
        c, _ = self.jouer(pile)
        c.nettoyages[0]()
        fluides = pile.envois[1]
        premiere = min(m["time"] for m in fluides)
        self.assertGreater(premiere, max(m["time"] for m in pile.envois[0]), "les minutes fluides suivent les congestionnées")
        self.assertEqual(len(fluides), 4 * 4 * flux.MESURES_PAR_MINUTE)

    def test_un_statut_refuse_est_un_echec(self):
        with self.assertRaises(u.Echec):
            self.jouer(PileFausse(statuts=["ACCEPTED"] * 95 + ["DUPLICATE"]))


class Indicateur(unittest.TestCase):
    def jouer(self, **kwargs):
        with mock.patch.object(u.flux, "attendre", attendre_une_fois):
            return u.u2_indicateur(contexte(PileFausse(**kwargs)))

    def test_des_etats_conformes_a_la_regle_de_seuils_passent(self):
        self.assertIn("égaux à ceux de la règle de seuils", self.jouer())

    def test_un_tronçon_dont_un_etat_differe_est_nomme(self):
        faux = {t: ATTENDUS for t in TRONCONS}
        faux["ROAD_019"] = ["FREE_FLOW", "SLOW", "CONGESTED", "CONGESTED"]
        with self.assertRaises(u.Echec) as erreur:
            self.jouer(etats=faux)
        self.assertIn("ROAD_019", str(erreur.exception))

    def test_un_tronçon_sans_indicateur_ou_une_api_en_erreur_est_un_echec(self):
        with self.assertRaises(u.Echec):
            self.jouer(etats={t: ATTENDUS for t in TRONCONS[:3]})
        with self.assertRaises(u.Echec):
            self.jouer(statut_indicateurs=503)


def alerte(troncon, **plus):
    return {"troncon": troncon, "regle": "congestion.persistante", "kind": "CONGESTION", "gravite": "WARNING", "etat": "NOTIFIED",
            "resolution": "", "alert_id": f"id-{troncon}", **plus}


def publique(troncon, **plus):
    return {"alert_id": f"id-{troncon}", "road_segment_id": troncon, "intersection_id": "INT_05", "severity": "WARNING",
            "opened_at": "2026-11-21T14:50:00Z", "simulated": True, **plus}


class Alerte(unittest.TestCase):
    def jouer(self, base=None, publiques=None, en_tetes=None):
        base = base if base is not None else [alerte(t) for t in TRONCONS]
        publiques = publiques if publiques is not None else [publique(t) for t in TRONCONS]
        en_tetes = en_tetes if en_tetes is not None else {"cache-control": "public, max-age=5"}
        c = contexte()
        with mock.patch.object(u.flux, "attendre", attendre_une_fois), mock.patch.object(u.flux, "alertes", return_value=base), \
                mock.patch.object(u, "lire_public", return_value=(200, en_tetes, {"items": publiques})):
            return c, u.u3_alerte(c)

    def test_quatre_alertes_creees_et_publiques_passent_et_sont_gardees_pour_la_suite(self):
        c, texte = self.jouer()
        self.assertIn("six champs publics", texte)
        self.assertEqual([a["troncon"] for a in c.notes["alertes"]], TRONCONS)

    def test_un_champ_interne_en_plus_dans_l_api_publique_est_un_echec(self):
        with self.assertRaises(u.Echec) as erreur:
            self.jouer(publiques=[publique(t, acknowledged_by="operateur1") if t == "ROAD_018" else publique(t) for t in TRONCONS])
        self.assertIn("acknowledged_by", str(erreur.exception))

    def test_une_donnee_non_simulee_est_un_echec(self):
        with self.assertRaises(u.Echec):
            self.jouer(publiques=[publique(t, simulated=False) for t in TRONCONS])

    def test_un_cache_different_de_cinq_secondes_est_un_echec(self):
        with self.assertRaises(u.Echec):
            self.jouer(en_tetes={"cache-control": "public, max-age=60"})
        with self.assertRaises(u.Echec):
            self.jouer(en_tetes={})

    def test_moins_de_quatre_alertes_ou_une_mauvaise_regle_est_un_echec(self):
        with self.assertRaises(u.Echec):
            self.jouer(base=[alerte(t) for t in TRONCONS[:3]])
        with self.assertRaises(u.Echec):
            self.jouer(base=[alerte(t, regle="autre") for t in TRONCONS])
        with self.assertRaises(u.Echec):
            self.jouer(base=[alerte(t, etat="RESOLVED") for t in TRONCONS])

    def test_une_alerte_absente_de_l_api_publique_est_un_echec(self):
        with self.assertRaises(u.Echec):
            self.jouer(publiques=[publique(t) for t in TRONCONS[:3]])


class VerdictAttendu(unittest.TestCase):
    """Le parcours calcule ce que le citoyen doit lire ; la règle est celle de `citizen/src/verdict.ts` (ADR-031, D2)."""

    def test_le_pire_etat_l_emporte(self):
        self.assertEqual(u.verdict_attendu(["FREE_FLOW", "FREE_FLOW"]), "Libre")
        self.assertEqual(u.verdict_attendu(["FREE_FLOW", "SLOW"]), "Ralenti")
        self.assertEqual(u.verdict_attendu(["SLOW", "CONGESTED"]), "Bloqué")
        self.assertEqual(u.verdict_attendu(["UNKNOWN", "CONGESTED"]), "Bloqué")
        self.assertEqual(u.verdict_attendu(["UNKNOWN", "SLOW"]), "Ralenti")

    def test_sans_mesure_ou_a_moitie_l_application_dit_sa_prudence(self):
        self.assertEqual(u.verdict_attendu(["UNKNOWN", "UNKNOWN"]), "Information indisponible")
        self.assertEqual(u.verdict_attendu(["FREE_FLOW", "UNKNOWN"]), "Information incomplète")
        self.assertNotEqual(u.verdict_attendu([]), "Libre", "un trajet sans tronçon n'est jamais Libre")

    def test_les_titres_sont_ceux_du_fichier_typescript(self):
        ts = (RACINE / "citizen" / "src" / "verdict.ts").read_text(encoding="utf-8")
        titres = dict(re.findall(r'(LIBRE|RALENTI|BLOQUE|INCOMPLET|INDISPONIBLE): "([^"]+)",\n', ts.split("VERDICT_TITRE")[1].split("};")[0] + "\n"))
        self.assertEqual(titres, u.VERDICTS, "le Python et le TypeScript ne disent plus les mêmes mots")

    def test_les_etats_publics_viennent_de_l_api_et_un_troncon_absent_est_inconnu(self):
        corps = {"items": [{"road_segment_id": "ROAD_017", "state": "CONGESTED"}, {"road_segment_id": "ROAD_018", "state": "FREE_FLOW"}]}
        with mock.patch.object(u, "lire_public", return_value=(200, {}, corps)):
            self.assertEqual(u.etats_publics(PileFausse(), ["ROAD_017", "ROAD_018", "ROAD_019"]), ["CONGESTED", "FREE_FLOW", "UNKNOWN"])
        with mock.patch.object(u, "lire_public", return_value=(503, {}, None)), self.assertRaises(u.Echec):
            u.etats_publics(PileFausse(), ["ROAD_017"])


class RejetsDuFutur(unittest.TestCase):
    """E1 (CLD-13) compte les rejets du flux dans `processing_stats` : la copie dans `rejects` est ignorée quand son identifiant existe déjà."""

    class MongoFaux:
        def __init__(self, sortie):
            self.sortie, self.expressions = sortie, []

        def mongo(self, expression):
            self.expressions.append(expression)
            return self.sortie

    def test_le_compteur_vient_de_processing_stats_pas_de_rejects(self):
        pile = self.MongoFaux("12")
        self.assertEqual(parcours.rejets_futurs(pile), 12)
        self.assertIn("processing_stats", pile.expressions[0])
        self.assertIn("FUTURE_TIMESTAMP", pile.expressions[0])
        self.assertNotIn("db.rejects", pile.expressions[0])

    def test_une_sortie_avec_des_avertissements_ou_vide_est_lue_sans_erreur(self):
        self.assertEqual(parcours.rejets_futurs(self.MongoFaux("Current Mongosh Log ID: x\n7")), 7)
        self.assertEqual(parcours.rejets_futurs(self.MongoFaux("")), 0)
        self.assertEqual(parcours.rejets_futurs(self.MongoFaux("0")), 0)


class Navigateur(unittest.TestCase):
    def faux(self, evenements, termine=False):
        n = u.Navigateur.__new__(u.Navigateur)
        n.evenements = queue.Queue()
        for e in evenements:
            n.evenements.put(e)
        n.processus = mock.Mock()
        n.processus.poll.return_value = 0 if termine else None
        return n

    def test_il_rend_le_compte_rendu_demande_et_ignore_les_autres(self):
        n = self.faux([{"evenement": "affichage", "ok": True}, {"evenement": "pret"}])
        self.assertEqual(n.attendre("pret", 2), {"evenement": "pret"})

    def test_une_erreur_du_script_est_un_echec_avec_son_message(self):
        n = self.faux([{"evenement": "erreur", "message": "Timeout 60000ms"}])
        with self.assertRaises(u.Echec) as erreur:
            n.attendre("pret", 2)
        self.assertIn("Timeout 60000ms", str(erreur.exception))

    def test_un_script_termine_sans_le_compte_rendu_attendu_est_un_echec(self):
        with self.assertRaises(u.Echec):
            self.faux([], termine=True).attendre("pret", 2)


class EssaiManuel(unittest.TestCase):
    def test_l_action_est_declaree_et_le_module_se_charge(self):
        import citoyen_manuel

        self.assertIn("manuel", dev.CITIZEN_ACTIONS)
        self.assertTrue(callable(citoyen_manuel.executer))

    def test_les_alertes_sont_refermees_meme_apres_une_interruption(self):
        import citoyen_manuel as m

        pile = PileFausse()
        pile.sante = lambda: True
        envois = []
        with mock.patch.object(m.flux, "Pile", return_value=pile), mock.patch.object(m.delai, "lire_env", return_value={}), \
                mock.patch.object(m.delai, "choisir_carrefour", return_value=5), \
                mock.patch.object(m.flux, "envoyer_run", side_effect=lambda c, run, carrefour, debut, plan, premiere: envois.append(plan)), \
                mock.patch.object(m.delai, "creations", return_value={f"i{n}": (f"ROAD_01{n}", 1.0) for n in range(4)}):
            reponses = iter(["", KeyboardInterrupt()])

            def entree(_):
                rep = next(reponses)
                if isinstance(rep, BaseException):
                    raise rep
                return rep

            self.assertEqual(m.executer(entree=entree, sortie=lambda *_: None), 0)
        self.assertEqual(envois, [m.delai.CONGESTIONNEES, m.delai.FLUIDES], "congestionnées d'abord, fluides à la fin")

    def test_rien_n_est_envoye_si_l_utilisateur_n_a_jamais_appuye(self):
        import citoyen_manuel as m

        pile = PileFausse()
        pile.sante = lambda: True
        envois = []
        with mock.patch.object(m.flux, "Pile", return_value=pile), mock.patch.object(m.delai, "lire_env", return_value={}), \
                mock.patch.object(m.delai, "choisir_carrefour", return_value=5), \
                mock.patch.object(m.flux, "envoyer_run", side_effect=lambda *a: envois.append(a)):
            def entree(_):
                raise EOFError

            m.executer(entree=entree, sortie=lambda *_: None)
        self.assertEqual(envois, [], "aucune mesure, donc rien à refermer")


class Cablage(unittest.TestCase):
    def test_les_ordres_du_python_sont_ceux_que_le_script_attend(self):
        script = (RACINE / "citizen" / "scripts" / "parcours-usager.mjs").read_text(encoding="utf-8")
        source = (RACINE / "scripts" / "dev" / "parcours_usager.py").read_text(encoding="utf-8")
        for ordre in re.findall(r'navigateur\.dire\("(\w+)"\)', source):
            self.assertIn(f'"{ordre}"', script)
        for evenement in ("affichage", "pret", "panne_page_ouverte", "panne_page_neuve", "attente_reprise", "reprise"):
            self.assertIn(f'evenement: "{evenement}"', script)
            self.assertIn(f'"{evenement}"', source)

    def test_la_panne_jouee_est_celle_du_service_qui_sert_mes_trajets(self):
        self.assertEqual(u.SERVICE_CIRCULATION, "traitement")
        source = (RACINE / "scripts" / "dev" / "parcours_usager.py").read_text(encoding="utf-8")
        self.assertIn("/api/v1/public/congestion", source)
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertRegex(compose, r"(?m)^  traitement:", "le service existe dans la pile")

    def test_la_passerelle_borne_la_connexion_aux_services_publics(self):
        conf = (RACINE / "gateway" / "citoyen.conf").read_text(encoding="utf-8")
        valeur = re.search(r"(?m)^proxy_connect_timeout (\d+)s;", conf)
        self.assertIsNotNone(valeur, "sans borne, la première requête vers un service arrêté attend 60 s")
        self.assertLessEqual(int(valeur.group(1)), 5)

    def test_dev_py_parcours_accepte_les_cas_de_l_usager_et_refuse_les_autres(self):
        args = dev.build_parser().parse_args(["parcours", "u1", "U5"])
        self.assertEqual(args.cas, ["u1", "U5"])

    def test_le_script_n_a_acces_qu_a_l_application_et_pas_a_un_reseau_exterieur(self):
        script = (RACINE / "citizen" / "scripts" / "parcours-usager.mjs").read_text(encoding="utf-8")
        for adresse in re.findall(r"https?://[\w.:-]+", script):
            self.assertTrue(adresse.startswith(("http://127.0.0.1", "http://localhost")), adresse)

    def test_les_captures_du_parcours_ont_chacune_leur_fichier(self):
        source = (RACINE / "scripts" / "dev" / "parcours_usager.py").read_text(encoding="utf-8")
        fichiers = re.findall(r'CAPTURES / "(CIT-07-[\w-]+\.png)"', source)
        self.assertEqual(len(fichiers), len(set(fichiers)), "deux captures ne s'écrasent pas")
        self.assertEqual(len(fichiers), 3)


if __name__ == "__main__":
    unittest.main()
