"""L'observatoire des pannes (CLD-13 : la panne contrôlée, CLD-14) : alarmes, cause, rapport et garde de l'interface, sans Docker.

Docker est remplacé par `FauxDocker`, les sondes par une fonction, l'horloge par un compteur : chaque test dit ce qu'il prouve.
Lancement : python3 -m unittest discover -s scripts/dev -p "test_observatoire.py"  (Windows : py -3 ...).
"""

import json
import re
import socket
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import observatoire as o

RACINE = Path(__file__).resolve().parents[2]


def trouver_port() -> int:
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return prise.getsockname()[1]


class Horloge:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def avancer(self, secondes):
        self.t += secondes


class FauxDocker:
    """Une pile minuscule : l'état des conteneurs et le texte du journal sont ceux que le test fabrique."""

    def __init__(self, config):
        self.conteneurs_ = {nom: {"etat": "running", "sante": "healthy", "code": 0, "statut": "Up 5 minutes", "id": nom} for nom in config["services"]}
        self.lignes = {}
        self.appels = []

    def conteneurs(self):
        return {nom: dict(valeur) for nom, valeur in self.conteneurs_.items()}

    def journaux(self, depuis=None, service=None, dernieres=None):
        sortie = []
        for nom, lignes in self.lignes.items():
            if service in (None, nom):
                sortie += [f"{nom}-1  | {ligne}" for ligne in lignes]
        return "\n".join(sortie)

    def kafka_groupes(self):
        return None  # pas de broker dans ces essais : le tableau n'a pas de retard à montrer

    def journaux_horodates(self, depuis):
        return ""

    def geler(self, service):
        self.appels.append(("pause", service))
        self.conteneurs_[service].update(etat="paused", sante="", statut="Up 5 minutes (Paused)")

    def degeler(self, service):
        self.appels.append(("unpause", service))
        self.conteneurs_[service].update(etat="running", sante="healthy", statut="Up 5 minutes")

    def arreter(self, service):
        self.appels.append(("stop", service))
        self.conteneurs_[service].update(etat="exited", sante="", code=0, statut="Exited (0) 3 seconds ago")
        self.lignes.setdefault(service, []).append('{"level": "INFO", "message": "Shutting down"}')

    def demarrer(self, service):
        self.appels.append(("start", service))
        self.conteneurs_[service].update(etat="running", sante="healthy", code=0, statut="Up 2 seconds")

    def inspecter(self, service):
        c = self.conteneurs_[service]
        return {"etat": c["etat"], "code": c["code"], "oom": False, "erreur": "", "sante": c["sante"], "pause": c["etat"] == "paused"}


def fabriquer(config=None):
    config = config or o.charger_config()
    docker = FauxDocker(config)
    horloge = Horloge()
    sante = {"collecte": True}  # service -> la sonde répond-elle

    def sonder(url, delai):
        # Une sonde est en échec quand un service qu'elle traverse est arrêté : le nom est lu dans l'adresse de la table des sondes.
        for sonde in obs.sondes:
            if sonde["url"] == url:
                return all(docker.conteneurs_.get(s, {}).get("etat") == "running" for s in sonde["traverse"]), "HTTP 200"
        return False, "inconnue"

    obs = o.Observatoire(config, docker, {}, horloge=horloge, sonder=sonder)
    obs.tableau.lire = lambda url: None  # aucun accès réseau : ces essais ne lisent jamais la vraie pile
    return obs, docker, horloge, sante


class Configuration(unittest.TestCase):
    def test_le_fichier_du_depot_est_valide_et_complet(self):
        config = o.charger_config()
        self.assertEqual({a["id"] for a in config["alarmes"]}, {"service-arrete", "sonde-http", "erreurs-journal", "disjoncteur-ouvert", "taux-erreurs-http", "retard-consommation"})
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        for nom in config["services"]:
            self.assertRegex(compose, rf"(?m)^  {nom}:$", f"{nom} n'est pas un service de docker-compose.yml")

    def test_chaque_alarme_renvoie_a_un_titre_d_un_guide_qui_existe(self):
        for alarme in o.charger_config()["alarmes"]:
            fichier, _, ancre = alarme["guide"].partition("#")
            guide = (RACINE / "docs" / "08-exploitation" / fichier).read_text(encoding="utf-8")
            ancres = {re.sub(r"[^\w\- ]", "", titre.lower()).replace(" ", "-") for titre in re.findall(r"(?m)^#{2,3} (.+)$", guide)}
            self.assertIn(fichier, ("diagnostic.md", "observabilite.md"), alarme["id"])
            self.assertIn(ancre, ancres, f"{alarme['id']} : pas de titre « {ancre} » dans {fichier}")

    def test_chaque_service_a_un_effet_documente_et_un_role(self):
        for nom, service in o.charger_config()["services"].items():
            self.assertTrue(service["effet"].strip() and service["role"].strip(), nom)

    def test_une_dependance_inconnue_est_refusee(self):
        config = o.charger_config()
        config["services"]["collecte"]["depend_de"].append("fantome")
        chemin = Path(self.id() + ".json")
        try:
            chemin.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(o.ErreurConfiguration):
                o.charger_config(chemin)
        finally:
            chemin.unlink(missing_ok=True)

    def test_les_dependants_sont_transitifs(self):
        config = o.charger_config()
        self.assertEqual(o.dependants(config, "collecte"), ["simulateur"])
        self.assertEqual(o.dependants(config, "traitement"), ["frontend", "passerelle"])
        self.assertIn("frontend", o.dependants(config, "postgres"))
        self.assertEqual(o.dependants(config, "frontend"), [])

    def test_les_sondes_suivent_les_ports_du_env_et_ajoutent_les_chaines(self):
        sondes = {s["id"]: s for s in o.sondes_declarees(o.charger_config(), {"COLLECTE_PORT": "9101"})}
        self.assertEqual(sondes["collecte"]["url"], "http://127.0.0.1:9101/api/v1/health")
        self.assertEqual(sondes["passerelle-vers-traitement"]["traverse"], ["passerelle", "traitement"])
        self.assertNotIn("postgres", sondes)


class Journaux(unittest.TestCase):
    def test_le_prefixe_de_compose_est_retire_meme_pour_un_nom_a_tiret(self):
        sortie = 'traitement-flux-1  | {"level": "INFO"}\npasserelle-1  | 127.0.0.1 "GET /health" 200 0.000 abc'
        self.assertEqual(o.decouper_journal(sortie), {"traitement-flux": ['{"level": "INFO"}'], "passerelle": ['127.0.0.1 "GET /health" 200 0.000 abc']})

    def test_ce_qui_est_une_erreur(self):
        self.assertTrue(o.est_une_erreur('{"level": "ERROR", "message": "x"}'))
        self.assertTrue(o.est_une_erreur('{"level": "critical"}'))
        self.assertFalse(o.est_une_erreur('{"level": "INFO", "message": "ERROR dans le texte"}'))
        self.assertTrue(o.est_une_erreur("2026/11/17 13:22:20 [error] 32#32: *328 connect() failed"))
        self.assertTrue(o.est_une_erreur('172.19.0.1 - - [17/Nov] "GET /api/v1/health HTTP/1.1" 503 259 "-"'))
        self.assertFalse(o.est_une_erreur('172.19.0.1 - - [17/Nov] "GET /health HTTP/1.1" 200 2 "-"'))
        self.assertFalse(o.est_une_erreur("{pas du json"))


class Alarmes(unittest.TestCase):
    def setUp(self):
        self.obs, self.docker, self.horloge, _ = fabriquer()

    def tour(self):
        self.horloge.avancer(5)
        self.obs.tour()

    def alarmes(self):
        return {(a["alarme"], a["cible"]) for a in self.obs.etat()["alarmes"] if a["etat"] == o.ALARME}

    def test_une_pile_saine_ne_leve_aucune_alarme_ni_evenement(self):
        for _ in range(3):
            self.tour()
        self.assertEqual(self.alarmes(), set())
        self.assertEqual(self.obs.chronologie(), [])
        self.assertTrue(self.obs.tout_est_ok())

    def test_il_faut_deux_mesures_defaillantes_de_suite_pour_lever_l_alarme(self):
        self.tour()
        self.obs.injecter("traitement")
        self.tour()
        self.assertEqual(self.alarmes(), set(), "une seule mesure ne suffit pas (evaluations = 2)")
        self.tour()
        self.assertIn(("service-arrete", "traitement"), self.alarmes())
        self.assertIn(("sonde-http", "passerelle-vers-traitement"), self.alarmes())

    def test_le_delai_de_detection_est_mesure_depuis_l_injection(self):
        self.tour()
        self.obs.injecter("traitement")
        self.tour()
        self.tour()
        alarme = next(a for a in self.obs.rapport()["alarmes"] if a["alarme"] == "service-arrete")
        self.assertEqual(alarme["delai_detection_s"], 10.0)
        self.assertEqual(self.obs.rapport()["premiere_alarme_s"], 10.0)

    def test_le_service_rétabli_ramene_les_alarmes_a_ok_et_l_evenement_est_note(self):
        self.tour()
        self.obs.injecter("traitement")
        self.tour()
        self.tour()
        self.obs.retablir()
        self.tour()
        self.assertEqual(self.alarmes(), set())
        self.assertTrue(self.obs.tout_est_ok())
        self.assertTrue(any(e["type"] == "alarme" and e["vers"] == o.OK for e in self.obs.chronologie()))
        self.assertIsNotNone(self.obs.rapport()["retablissement"])

    def test_un_conteneur_absent_donne_des_donnees_insuffisantes_pas_une_alarme(self):
        del self.docker.conteneurs_["reponse"]
        self.tour()
        etat = next(a for a in self.obs.etat()["alarmes"] if a["alarme"] == "service-arrete" and a["cible"] == "reponse")
        self.assertEqual(etat["etat"], o.INSUFFISANT)

    def test_un_conteneur_malsain_leve_l_alarme_meme_s_il_tourne(self):
        self.docker.conteneurs_["alerte-worker"]["sante"] = "unhealthy"
        self.tour()
        self.tour()
        self.assertIn(("service-arrete", "alerte-worker"), self.alarmes())

    def test_les_erreurs_du_journal_levent_l_alarme_au_seuil_et_pas_avant(self):
        erreur = '{"level": "ERROR", "message": "boom"}'
        self.docker.lignes["collecte"] = [erreur, erreur]
        self.tour()
        self.assertNotIn(("erreurs-journal", "collecte"), self.alarmes())
        self.docker.lignes["collecte"].append(erreur)
        self.tour()
        self.assertIn(("erreurs-journal", "collecte"), self.alarmes())


class Cause(unittest.TestCase):
    def test_chaque_cause_a_son_constat(self):
        self.assertIn("arrêt ordonné", o.diagnostiquer({"etat": "exited", "code": 0}, ["Shutting down"])["constat"])
        self.assertIn("Shutting down", " ".join(o.diagnostiquer({"etat": "exited", "code": 0}, ["Shutting down"])["indices"]))
        self.assertIn("SIGKILL", o.diagnostiquer({"etat": "exited", "code": 137}, [])["constat"])
        self.assertIn("mémoire", o.diagnostiquer({"etat": "exited", "code": 137, "oom": True}, [])["constat"])
        self.assertIn("SIGTERM", o.diagnostiquer({"etat": "exited", "code": 143}, [])["constat"])
        plantage = o.diagnostiquer({"etat": "exited", "code": 1}, ['{"level": "ERROR", "message": "KeyError"}'])
        self.assertIn("code 1", plantage["constat"])
        self.assertTrue(any("KeyError" in i for i in plantage["indices"]))
        self.assertIn("bloqué", o.diagnostiquer({"etat": "running", "code": 0, "sante": "unhealthy"}, [])["constat"])


class Panne(unittest.TestCase):
    def setUp(self):
        self.obs, self.docker, self.horloge, _ = fabriquer()
        self.horloge.avancer(5)
        self.obs.tour()

    def test_un_service_inconnu_est_refuse(self):
        with self.assertRaises(o.ErreurPanne):
            self.obs.injecter("rm -rf")
        self.assertEqual(self.docker.appels, [])

    def test_le_socle_demande_une_confirmation(self):
        with self.assertRaises(o.ErreurPanne):
            self.obs.injecter("postgres")
        self.assertEqual(self.docker.appels, [])
        self.obs.injecter("postgres", confirmer=True)
        self.assertEqual(self.docker.appels, [("stop", "postgres")])

    def test_une_seule_panne_a_la_fois(self):
        self.obs.injecter("collecte")
        with self.assertRaises(o.ErreurPanne):
            self.obs.injecter("simulateur")
        self.assertEqual(self.docker.appels, [("stop", "collecte")])

    def test_retablir_sans_panne_est_refuse(self):
        with self.assertRaises(o.ErreurPanne):
            self.obs.retablir()

    def test_la_cause_vient_de_ce_que_docker_a_enregistre_et_reste_apres_le_retablissement(self):
        self.obs.injecter("traitement")
        for _ in range(2):
            self.horloge.avancer(5)
            self.obs.tour()
        self.obs.retablir()
        for _ in range(2):
            self.horloge.avancer(5)
            self.obs.tour()
        rapport = self.obs.rapport()
        self.assertIn("arrêt ordonné", rapport["cause"]["constat"])
        self.assertTrue(any("Shutting down" in ligne for ligne in rapport["journaux"]["traitement"]))

    def test_l_impact_prevu_et_l_impact_constate_sont_distincts(self):
        self.obs.injecter("traitement")
        for _ in range(2):
            self.horloge.avancer(5)
            self.obs.tour()
        impact = self.obs.rapport()["impact"]
        self.assertEqual(impact["prevu"], ["frontend", "passerelle"])
        self.assertEqual(impact["observe_en_alarme"], ["frontend", "passerelle"])

    def test_le_rapport_en_texte_a_ses_six_parties(self):
        self.obs.injecter("collecte")
        for _ in range(2):
            self.horloge.avancer(5)
            self.obs.tour()
        texte = o.rapport_texte(self.obs.rapport())
        for titre in ("1. Alarmes", "2. Journaux", "3. Tableau", "4. Cause", "5. Impact", "6. Chronologie"):
            self.assertIn(titre, texte)

    def test_rejouer_retablit_toujours_meme_si_l_alarme_ne_vient_pas(self):
        self.obs.sonder = lambda url, delai: (True, "HTTP 200")
        self.docker.arreter = lambda service: self.docker.appels.append(("stop", service))  # le conteneur reste « running »
        rapport = o.rejouer_panne(self.obs, "collecte", duree_s=0, attente_alarme_s=0, attente_reprise_s=0, afficher=lambda _: None, attendre=lambda _: None)
        self.assertEqual(self.docker.appels, [("stop", "collecte"), ("start", "collecte")])
        self.assertEqual(rapport["alarmes"], [])


class GardeDeLInterface(unittest.TestCase):
    def test_un_hote_etranger_est_refuse_meme_en_lecture(self):
        self.assertTrue(o.requete_autorisee("127.0.0.1:8090", None, None, "j", 8090, False))
        self.assertTrue(o.requete_autorisee("localhost:8090", None, None, "j", 8090, False))
        self.assertFalse(o.requete_autorisee("evil.example:8090", None, None, "j", 8090, False))
        self.assertFalse(o.requete_autorisee(None, None, None, "j", 8090, False))
        self.assertFalse(o.requete_autorisee("127.0.0.1:9999", None, None, "j", 8090, False))

    def test_une_ecriture_exige_origine_identique_et_jeton_exact(self):
        bon = ("127.0.0.1:8090", "http://127.0.0.1:8090", "secret", "secret", 8090, True)
        self.assertTrue(o.requete_autorisee(*bon))
        self.assertFalse(o.requete_autorisee("127.0.0.1:8090", "http://evil.example", "secret", "secret", 8090, True))
        self.assertFalse(o.requete_autorisee("127.0.0.1:8090", None, "secret", "secret", 8090, True))
        self.assertFalse(o.requete_autorisee("127.0.0.1:8090", "http://127.0.0.1:8090", "autre", "secret", 8090, True))
        self.assertFalse(o.requete_autorisee("127.0.0.1:8090", "http://127.0.0.1:8090", None, "secret", 8090, True))


class ServeurHttp(unittest.TestCase):
    JETON = "jeton-de-test"

    @classmethod
    def setUpClass(cls):
        cls.obs, cls.docker, cls.horloge, _ = fabriquer()
        cls.obs.tour()
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
                return reponse.status, reponse.read().decode(), reponse.headers
        except urllib.error.HTTPError as erreur:
            return erreur.code, erreur.read().decode(), erreur.headers

    def ecriture(self, chemin, corps):
        return self.appel(chemin, corps, {"Origin": f"http://127.0.0.1:{self.port}", "X-Observatoire-Jeton": self.JETON})

    def test_la_page_porte_le_jeton_et_des_entetes_de_securite(self):
        statut, corps, entetes = self.appel("/")
        self.assertEqual(statut, 200)
        self.assertIn(self.JETON, corps)
        self.assertNotIn("__JETON__", corps)
        self.assertEqual(entetes["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", entetes["Content-Security-Policy"])
        self.assertEqual(entetes["Cache-Control"], "no-store")

    def test_la_page_n_ecrit_aucune_donnee_dans_du_html_en_clair(self):
        page = (RACINE / "ops" / "observatoire" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn(".innerHTML", page, "les lignes de journal sont du texte non fiable : textContent seulement")
        self.assertNotIn("eval(", page)

    def test_l_etat_est_en_json_et_un_chemin_inconnu_donne_404(self):
        statut, corps, _ = self.appel("/api/etat")
        self.assertEqual(statut, 200)
        self.assertEqual(len(json.loads(corps)["services"]), len(o.charger_config()["services"]))
        self.assertEqual(self.appel("/../../etc/passwd")[0], 404)
        self.assertEqual(self.appel("/api/inconnu")[0], 404)

    def test_un_hote_etranger_est_refuse(self):
        self.assertEqual(self.appel("/api/etat", entetes={"Host": "evil.example"})[0], 403)

    def test_arreter_sans_jeton_ou_sans_origine_est_refuse_et_rien_n_est_arrete(self):
        self.assertEqual(self.appel("/api/panne", {"service": "collecte"})[0], 403)
        self.assertEqual(self.appel("/api/panne", {"service": "collecte"}, {"X-Observatoire-Jeton": self.JETON})[0], 403)
        self.assertEqual(self.appel("/api/panne", {"service": "collecte"}, {"Origin": f"http://127.0.0.1:{self.port}"})[0], 403)
        self.assertNotIn(("stop", "collecte"), self.docker.appels)

    def test_un_service_inconnu_et_le_socle_sans_confirmation_donnent_409(self):
        self.assertEqual(self.ecriture("/api/panne", {"service": "autre"})[0], 409)
        self.assertEqual(self.ecriture("/api/panne", {"service": "kafka"})[0], 409)
        self.assertEqual(self.ecriture("/api/panne", {"service": "kafka", "confirmer": "oui"})[0], 409, "seul le booléen vrai confirme")

    def test_le_parcours_arret_puis_retablissement_par_l_interface(self):
        statut, _, _ = self.ecriture("/api/panne", {"service": "reponse"})
        self.assertEqual(statut, 200)
        self.assertEqual(self.ecriture("/api/panne", {"service": "alerte"})[0], 409, "une seule panne à la fois")
        self.assertEqual(self.appel("/api/etat")[0], 200)
        statut, corps, _ = self.ecriture("/api/retablir", {})
        self.assertEqual(statut, 200)
        self.assertEqual(self.docker.appels[-2:], [("stop", "reponse"), ("start", "reponse")])
        self.assertEqual(self.ecriture("/api/retablir", {})[0], 409)

    def test_un_corps_illisible_donne_400(self):
        requete = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/panne", data=b"{pas du json", method="POST",
                                         headers={"Origin": f"http://127.0.0.1:{self.port}", "X-Observatoire-Jeton": self.JETON})
        with self.assertRaises(urllib.error.HTTPError) as erreur:
            urllib.request.urlopen(requete, timeout=10)
        self.assertEqual(erreur.exception.code, 400)
        erreur.exception.close()


if __name__ == "__main__":
    unittest.main()
