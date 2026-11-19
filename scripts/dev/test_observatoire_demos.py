"""Démonstrations de l'observatoire (flux complet, sécurité, cloud local, IA) : liste fermée, garde, exécution, constat, synthèse.

Aucun Docker ni aucune vraie commande : le lanceur de processus est remplacé, les inspections Docker sont fabriquées.
Lancement : python3 -m unittest discover -s scripts/dev -p "test_observatoire_demos.py"  (Windows : py -3 ...).
"""

import io
import json
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import observatoire as o
import observatoire_demos as d
from test_observatoire import FauxDocker, fabriquer, trouver_port

RACINE = Path(__file__).resolve().parents[2]


class FauxProcessus:
    def __init__(self, lignes, code=0, attente=0.0):
        self.stdout = io.StringIO("".join(f"{ligne}\n" for ligne in lignes))
        self.code, self.attente, self.arrete = code, attente, False

    def wait(self):
        time.sleep(self.attente)
        return -15 if self.arrete else self.code

    def terminate(self):
        self.arrete = True


def lanceur(lignes, code=0, attente=0.0, appels=None):
    def lancer(commande, **_):
        if appels is not None:
            appels.append(commande)
        return FauxProcessus(lignes, code, attente)

    return lancer


def attendre(taches, etat_final=("ok", "echec", "arrete")):
    for _ in range(300):
        c = taches.etat()["courante"]
        if c and c["etat"] in etat_final:
            return c
        time.sleep(0.01)
    raise AssertionError("la démonstration ne s'est pas terminée")


class Catalogue(unittest.TestCase):
    def test_chaque_theme_a_des_demonstrations_et_les_identifiants_sont_uniques(self):
        self.assertEqual(len({x.identifiant for x in d.DEMOS}), len(d.DEMOS))
        self.assertEqual({x.theme for x in d.DEMOS}, set(d.THEMES))

    def test_chaque_commande_existe_dans_dev_py(self):
        sous_commandes = set(re.findall(r'add\("([a-z0-9-]+)"', (RACINE / "scripts" / "dev" / "dev.py").read_text(encoding="utf-8")))
        for demo in d.DEMOS:
            if demo.arguments[0] == "__tests__":
                self.assertTrue((RACINE / "scripts" / "dev" / demo.arguments[1]).is_file(), demo.identifiant)
            else:
                self.assertIn(demo.arguments[0], sous_commandes, demo.identifiant)

    def test_les_cas_du_flux_sont_ceux_de_flux_complet(self):
        import flux_complet

        connus = {c[0] for c in flux_complet.CAS}
        for demo in d.DEMOS:
            if demo.theme == "flux":
                self.assertLessEqual(set(demo.arguments[1:]), connus, demo.identifiant)

    def test_un_cas_qui_arrete_des_conteneurs_est_declare_comme_tel(self):
        for demo in d.DEMOS:
            if demo.theme == "flux":
                self.assertEqual(demo.arrete_des_conteneurs, any(c.startswith("F") and c != "F1" for c in demo.arguments[1:]), demo.identifiant)

    def test_aucune_demonstration_n_ecrit_dans_le_depot(self):
        self.assertFalse([x.identifiant for x in d.DEMOS if x.ecrit_dans_le_depot])
        for demo in d.DEMOS:  # les évaluations IA écrivent ml/evaluation (fichiers suivis) : elles ne sont pas rejouables d'ici
            self.assertNotIn(demo.arguments[0], ("ml-anomalies", "ml-prevision"))
            self.assertNotIn("comparer", demo.arguments)

    def test_la_presentation_couvre_chaque_theme_avec_sa_preuve_ecrite(self):
        presentation = d.charger_presentation()
        for theme in d.THEMES:
            bloc = presentation[theme]
            self.assertTrue(bloc["titre"] and bloc["message"] and bloc["etapes"], theme)
            self.assertTrue((RACINE / bloc["doc"]).is_file(), f"{theme} : {bloc['doc']} est introuvable")
        self.assertTrue(presentation["securite"]["reste"], "ce qui reste à corriger est dit, pas seulement ce qui est corrigé")


class Commandes(unittest.TestCase):
    def test_la_graine_est_un_entier_et_rien_d_autre(self):
        sumo = d.PAR_ID["ia-sumo"]
        for mauvaise in ("1; rm -rf /", "-1", "abc", "1234567"):
            with self.assertRaises(ValueError, msg=mauvaise):
                d.commandes(sumo, mauvaise)
        suite = d.commandes(sumo, "7")
        self.assertEqual([c[-2:] for c in suite], [["--graine", "7"], ["--graine", "7"]])
        self.assertNotIn("--pile", suite[1])

    def test_le_rejeu_sur_la_pile_ajoute_pile_au_seul_rejeu(self):
        suite = d.commandes(d.PAR_ID["ia-sumo-pile"], "9")
        self.assertNotIn("--pile", suite[0])
        self.assertIn("--pile", suite[1])

    def test_aucune_commande_ne_passe_par_un_interpreteur_de_commandes(self):
        for demo in d.DEMOS:
            for commande in d.commandes(demo):
                self.assertIsInstance(commande, list)
                self.assertFalse({"sh", "bash", "-c", "cmd", "powershell"} & set(commande), demo.identifiant)

    def test_les_resultats_du_flux_sont_lus_dans_la_sortie(self):
        lignes = ["[OK] N1  Compte opérateur (1.2 s) : créé", "bruit", "[ÉCHEC] F2  Service arrêté : lecture 3 au lieu de 2"]
        self.assertEqual(d.resumer(lignes), [{"ok": True, "cas": "N1", "texte": "Compte opérateur (1.2 s) : créé"},
                                              {"ok": False, "cas": "F2", "texte": "Service arrêté : lecture 3 au lieu de 2"}])


class Execution(unittest.TestCase):
    def test_une_demonstration_reussie_garde_sa_sortie_et_son_resultat(self):
        appels = []
        taches = d.Taches(lanceur=lanceur(["[OK] N1  Compte : ok", "1/1 cas satisfaits."], appels=appels))
        taches.demarrer("flux-f1", confirmer=False)
        c = attendre(taches)
        self.assertEqual((c["etat"], c["code"]), ("ok", 0))
        self.assertEqual(c["resultats"][0]["cas"], "N1")
        self.assertIn("1/1 cas satisfaits.", c["lignes"])
        self.assertEqual(taches.etat()["historique"]["flux-f1"]["etat"], "ok")
        self.assertNotIn("lignes", taches.etat()["historique"]["flux-f1"], "l'historique ne garde pas toute la sortie")
        self.assertEqual(appels[0][-2:], ["flux-complet", "F1"])

    def test_un_code_de_sortie_non_nul_est_un_echec(self):
        taches = d.Taches(lanceur=lanceur(["[ÉCHEC] F1  Message invalide : x"], code=1))
        taches.demarrer("flux-f1")
        self.assertEqual(attendre(taches)["etat"], "echec")

    def test_une_suite_s_arrete_au_premier_echec(self):
        appels = []
        taches = d.Taches(lanceur=lanceur(["boum"], code=1, appels=appels))
        taches.demarrer("ia-sumo", graine="5")
        attendre(taches)
        self.assertEqual(len(appels), 1, "le rejeu n'est pas lancé si la simulation a échoué")

    def test_un_cas_qui_arrete_des_conteneurs_exige_une_confirmation(self):
        taches = d.Taches(lanceur=lanceur([]))
        with self.assertRaises(PermissionError):
            taches.demarrer("flux-f3", confirmer=False)
        self.assertIsNone(taches.etat()["courante"])

    def test_pas_de_cas_qui_arrete_des_conteneurs_pendant_une_panne_controlee(self):
        taches = d.Taches(lanceur=lanceur([]))
        with self.assertRaises(RuntimeError):
            taches.demarrer("flux-f3", confirmer=True, panne_en_cours=True)

    def test_une_seule_demonstration_a_la_fois(self):
        taches = d.Taches(lanceur=lanceur(["x"], attente=0.3))
        taches.demarrer("securite-compose")
        with self.assertRaises(RuntimeError):
            taches.demarrer("securite-verrous")
        attendre(taches)

    def test_une_demonstration_inconnue_est_refusee(self):
        with self.assertRaises(KeyError):
            d.Taches(lanceur=lanceur([])).demarrer("rm-rf")

    def test_on_peut_interrompre_une_demonstration(self):
        taches = d.Taches(lanceur=lanceur(["x"], attente=0.5))
        taches.demarrer("securite-compose")
        taches.arreter()
        c = attendre(taches)
        self.assertEqual(c["etat"], "arrete")
        with self.assertRaises(RuntimeError):
            taches.arreter()

    def test_la_sortie_est_bornee(self):
        taches = d.Taches(lanceur=lanceur([f"ligne {i}" for i in range(d.LIGNES_MAX + 200)]))
        taches.demarrer("securite-compose")
        c = attendre(taches)
        self.assertEqual(len(c["lignes"]), d.LIGNES_MAX)
        self.assertEqual(c["lignes"][-1], f"ligne {d.LIGNES_MAX + 199}")

    def test_une_commande_introuvable_donne_un_echec_lisible(self):
        def lancer(*_, **__):
            raise FileNotFoundError("docker")

        taches = d.Taches(lanceur=lancer)
        taches.demarrer("securite-compose")
        c = attendre(taches)
        self.assertEqual((c["etat"], c["code"]), ("echec", 127))
        self.assertIn("FileNotFoundError", "\n".join(c["lignes"]))


def conteneur(service, *, cap_drop=("ALL",), securite=("no-new-privileges:true",), prive=False, reseau="bridge", ports=None, montages=(), user="appuser"):
    return {"Name": f"/novaria-{service}-1", "Config": {"User": user, "Labels": {"com.docker.compose.service": service}},
            "HostConfig": {"CapDrop": list(cap_drop), "SecurityOpt": list(securite), "Privileged": prive, "NetworkMode": reseau},
            "NetworkSettings": {"Ports": ports or {}}, "Mounts": [{"Source": m} for m in montages]}


class Securite(unittest.TestCase):
    def test_un_conteneur_durci_est_reconnu(self):
        c = d.evaluer_conteneur(conteneur("alerte", ports={"8003/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8003"}]}))
        self.assertTrue(c["cap_drop_all"] and c["no_new_privileges"])
        self.assertFalse(c["privilegie"] or c["reseau_hote"] or c["sock_docker"])
        self.assertEqual(c["ports_exposes"], [])

    def test_un_port_ouvert_au_reseau_est_signale(self):
        c = d.evaluer_conteneur(conteneur("collecte", ports={"8001/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8001"}]}))
        self.assertEqual(c["ports_exposes"], ["8001/tcp sur 0.0.0.0"])

    def test_un_port_non_publie_n_est_pas_un_port_expose(self):
        self.assertEqual(d.evaluer_conteneur(conteneur("x", ports={"5432/tcp": None}))["ports_exposes"], [])

    def test_privilege_reseau_hote_et_socket_docker_sont_signales(self):
        c = d.evaluer_conteneur(conteneur("x", prive=True, reseau="host", montages=("/var/run/docker.sock",), cap_drop=(), securite=()))
        self.assertTrue(c["privilegie"] and c["reseau_hote"] and c["sock_docker"])
        self.assertFalse(c["cap_drop_all"] or c["no_new_privileges"])

    def test_le_constat_liste_les_graves_et_triee_les_services(self):
        brut = [conteneur("reponse"), conteneur("alerte", prive=True)]
        constat = d.constat_securite(lambda: brut)
        self.assertEqual([c["service"] for c in constat["conteneurs"]], ["alerte", "reponse"])
        self.assertEqual(constat["graves"], ["alerte"])
        self.assertIn("à corriger : alerte", constat["resume"])

    def test_aucun_conteneur_n_est_pas_un_constat_de_conformite(self):
        constat = d.constat_securite(lambda: [])
        self.assertEqual(constat["conteneurs"], [])
        self.assertNotIn("aucun privilégié", constat["resume"])
        self.assertIn("Aucun conteneur en marche", constat["resume"])

    def test_docker_injoignable_est_dit_et_non_masque_par_un_succes(self):
        def casse():
            raise OSError("docker")

        constat = d.constat_securite(casse)
        self.assertFalse(constat["disponible"])
        self.assertEqual(constat["conteneurs"], [])

    def test_le_constat_reel_du_compose_est_en_accord_avec_la_revue(self):
        # La revue de sécurité affirme « dix services applicatifs durcis » : le fichier Compose doit encore le dire.
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("x-durcissement", compose)
        self.assertEqual(compose.count("<<: *durcissement"), 10)


class SyntheseIA(unittest.TestCase):
    def test_les_vrais_fichiers_donnent_une_synthese(self):
        s = d.synthese_ia()
        self.assertTrue(s["anomalies"])
        detecteurs = {x["detecteur"]: x for x in s["anomalies"]}
        self.assertGreater(detecteurs["regles"]["precision"], detecteurs["isolation_forest"]["precision"])
        self.assertIsNotNone(s["sumo"]["capacite_mesuree_vph"])
        self.assertTrue(s["prevision"]["horizons"])

    def test_un_fichier_absent_reste_absent(self):
        with tempfile.TemporaryDirectory() as dossier:
            s = d.synthese_ia(Path(dossier))
        self.assertEqual(s, {"anomalies": None, "prevision": None, "sumo": None, "detection": None})

    def test_un_fichier_illisible_n_est_pas_une_erreur(self):
        with tempfile.TemporaryDirectory() as dossier:
            (Path(dossier) / "anomalies.json").write_text("{pas du json", encoding="utf-8")
            self.assertIsNone(d.synthese_ia(Path(dossier))["anomalies"])


class FauxDockerComplet(FauxDocker):
    def inspecter_tous(self):
        return [conteneur("alerte"), conteneur("collecte", ports={"8001/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8001"}]})]


class ServeurHttp(unittest.TestCase):
    JETON = "jeton-de-test"

    @classmethod
    def setUpClass(cls):
        cls.obs, _, _, _ = fabriquer()
        cls.obs.docker = FauxDockerComplet(cls.obs.config)
        cls.obs.taches = d.Taches(lanceur=lanceur(["[OK] F1  Message invalide : refusé"]))
        cls.port = trouver_port()
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", cls.port), o.fabriquer_gestionnaire(cls.obs, cls.JETON, cls.port))
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()
        cls.serveur.server_close()

    def appel(self, chemin, corps=None, entetes=None):
        base = {"Content-Type": "application/json"} | (entetes or {})
        requete = urllib.request.Request(f"http://127.0.0.1:{self.port}{chemin}", data=None if corps is None else json.dumps(corps).encode(), headers=base)
        try:
            with urllib.request.urlopen(requete, timeout=10) as reponse:
                return reponse.status, json.loads(reponse.read().decode())
        except urllib.error.HTTPError as erreur:
            return erreur.code, json.loads(erreur.read().decode())

    def ecriture(self, chemin, corps):
        return self.appel(chemin, corps, {"Origin": f"http://127.0.0.1:{self.port}", "X-Observatoire-Jeton": self.JETON})

    def test_le_catalogue_et_la_presentation_sont_servis(self):
        statut, corps = self.appel("/api/demos")
        self.assertEqual(statut, 200)
        self.assertEqual(len(corps["demos"]), len(d.DEMOS))
        self.assertEqual(set(corps["presentation"]), set(d.THEMES))

    def test_lancer_une_demonstration_exige_le_jeton_et_l_origine(self):
        self.assertEqual(self.appel("/api/demos/lancer", {"id": "flux-f1"})[0], 403)
        self.assertEqual(self.appel("/api/demos/lancer", {"id": "flux-f1"}, {"X-Observatoire-Jeton": self.JETON})[0], 403)
        self.assertEqual(self.appel("/api/demos/arreter", {})[0], 403)

    def test_lancer_puis_lire_le_resultat(self):
        statut, corps = self.ecriture("/api/demos/lancer", {"id": "flux-f1"})
        self.assertEqual(statut, 200, corps)
        attendre(self.obs.taches)
        _, catalogue = self.appel("/api/demos")
        self.assertEqual(catalogue["courante"]["resultats"][0]["cas"], "F1")

    def test_un_identifiant_inconnu_ou_sans_confirmation_est_refuse(self):
        self.assertEqual(self.ecriture("/api/demos/lancer", {"id": "inconnu"})[0], 409)
        statut, corps = self.ecriture("/api/demos/lancer", {"id": "flux-f3"})
        self.assertEqual(statut, 409)
        self.assertIn("confirmation", corps["erreur"])

    def test_une_graine_invalide_est_refusee(self):
        statut, corps = self.ecriture("/api/demos/lancer", {"id": "ia-sumo", "graine": "1;ls"})
        self.assertEqual(statut, 409)
        self.assertIn("graine", corps["erreur"])

    def test_le_constat_de_securite_est_servi(self):
        statut, corps = self.appel("/api/securite")
        self.assertEqual(statut, 200)
        self.assertEqual(corps["graves"], ["collecte"])

    def test_la_synthese_ia_est_servie(self):
        statut, corps = self.appel("/api/ia")
        self.assertEqual(statut, 200)
        self.assertIn("anomalies", corps)


class Page(unittest.TestCase):
    PAGE = (RACINE / "ops" / "observatoire" / "index.html").read_text(encoding="utf-8")

    def test_les_quatre_onglets_existent(self):
        for vue in d.THEMES:
            self.assertIn(f'data-vue="{vue}"', self.PAGE)

    def test_la_page_n_utilise_toujours_que_du_texte(self):
        self.assertNotIn(".innerHTML", self.PAGE)
        self.assertNotIn("insertAdjacentHTML", self.PAGE)
        self.assertNotIn("eval(", self.PAGE)

    def test_les_confirmations_de_la_page_suivent_le_catalogue(self):
        self.assertIn("arrete_des_conteneurs", self.PAGE)
        self.assertIn("confirmer: d.arrete_des_conteneurs", self.PAGE)


if __name__ == "__main__":
    unittest.main()
