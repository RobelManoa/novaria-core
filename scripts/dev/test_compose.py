"""Contrôle de la pile Docker Compose multi-services (issue MS-06).

Critère d'acceptation : `dev.py up` démarre l'ensemble et chaque /health répond. Le démarrage réel se prouve par
`dev.py up` (voir docs/08-exploitation/pile-locale.md) ; ce test vérifie ce qui le rend possible et ce qui le garde
correct : chaque service du dépôt est dans Compose, l'ordre de démarrage ne repose que sur des sondes ou des tâches
terminées, les ports ne sortent pas de 127.0.0.1, la passerelle route chaque chemin des contrats vers le bon service,
et les sondes de `dev.py` savent dire « OK » et « KO ».

Dépendance : PyYAML (`pip install pyyaml`). Sans elle, les tests concernés sont ignorés, pas en échec.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_compose.py"   (Windows : py -3 ...)
"""
import argparse
import http.client
import http.server
import importlib.util
import json
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml
except ImportError:  # pragma: no cover - dépend du poste
    yaml = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
SERVICES_DU_DEPOT = sorted(p.name for p in (RACINE / "services").iterdir() if p.is_dir() and not p.name.startswith("_"))
APPLICATIFS = {"collecte", "traitement", "alerte", "reponse", "simulateur", "passerelle", "frontend"}
TACHES_UNIQUES = {"db-migrate", "kafka-init"}
# service -> (compte PostgreSQL, compte MongoDB) : un compte par service, aux droits minimaux (ADR-024)
# Services qui portent le rôle « API métier » (schéma app, jetons) en plus du leur, tant que le point ouvert n° 1
# des diagrammes C4 n'est pas tranché.
PORTE_L_API_METIER = {"traitement"}
COMPTES = {"collecte": (None, "svc_collecte"), "traitement": ("svc_traitement", "svc_traitement"),
           "alerte": ("svc_alerte", None), "reponse": (None, "svc_reponse")}
VARIABLES_DE_PORT = {"GATEWAY_PORT": 8000, "FRONTEND_PORT": 8080, "COLLECTE_PORT": 8001, "TRAITEMENT_PORT": 8002,
                     "ALERTE_PORT": 8003, "REPONSE_PORT": 8004, "SIMULATOR_PORT": 8005}


def compose() -> dict:
    return yaml.safe_load((RACINE / "docker-compose.yml").read_text(encoding="utf-8"))


def dependances(service: dict) -> dict[str, str]:
    """{service dont on dépend: condition}. Une dépendance sans condition vaut `service_started`."""
    declarees = service.get("depends_on", {})
    if isinstance(declarees, list):
        return {nom: "service_started" for nom in declarees}
    return {nom: contenu.get("condition", "service_started") for nom, contenu in declarees.items()}


def a_une_sonde(service: dict, services_compose: dict) -> bool:
    """Un service a une sonde de santé dans Compose ou dans le HEALTHCHECK du Dockerfile qui le construit."""
    if "healthcheck" in service:
        return True
    construction = service.get("build")
    if construction is None:
        return False
    dossier = construction if isinstance(construction, str) else construction["context"]
    dockerfile = RACINE / dossier / "Dockerfile"
    return dockerfile.is_file() and bool(re.search(r"(?m)^HEALTHCHECK ", dockerfile.read_text(encoding="utf-8")))


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class ServicesDeLaPile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = compose()
        cls.services = cls.doc["services"]

    def test_tout_est_dans_compose(self):
        attendus = {"postgres", "mongo", "kafka"} | TACHES_UNIQUES | APPLICATIFS
        sans_profil = {nom for nom, s in self.services.items() if "profiles" not in s}
        self.assertEqual(sans_profil, attendus)

    def test_chaque_service_du_depot_a_son_conteneur_et_inversement(self):
        construits = {nom: s["build"]["context"] for nom, s in self.services.items()
                      if isinstance(s.get("build"), dict) and s["build"]["context"].startswith("./services/")}
        self.assertEqual(sorted(Path(c).name for c in construits.values()), SERVICES_DU_DEPOT)
        for nom, contexte in construits.items():
            self.assertEqual(Path(contexte).name, nom, "le conteneur porte le nom de son dossier")

    def test_les_ports_ne_sont_publies_que_sur_la_boucle_locale(self):
        for nom, service in self.services.items():
            for port in service.get("ports", []):
                with self.subTest(service=nom, port=port):
                    self.assertTrue(port.startswith("127.0.0.1:"), "port joignable depuis le réseau")

    def test_les_ports_des_conteneurs_applicatifs_viennent_de_env_example(self):
        env = dev.parse_env((RACINE / ".env.example").read_text(encoding="utf-8"))
        for variable, defaut in VARIABLES_DE_PORT.items():
            with self.subTest(variable=variable):
                self.assertEqual(env[variable], str(defaut))
        texte = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        for variable, defaut in VARIABLES_DE_PORT.items():
            self.assertIn("${%s:-%d}" % (variable, defaut), texte)
        self.assertEqual(len(set(VARIABLES_DE_PORT.values())), len(VARIABLES_DE_PORT), "deux conteneurs, un même port")

    def test_aucun_conteneur_applicatif_ne_garde_l_ancien_nom_backend(self):
        texte = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotRegex(texte, r"(?m)^  backend:")
        self.assertNotIn("http://backend", (RACINE / "frontend" / "nginx.conf").read_text(encoding="utf-8"))

    def test_chaque_service_a_son_seul_compte_de_base(self):
        for nom, (compte_pg, compte_mongo) in COMPTES.items():
            environnement = self.services[nom]["environment"]
            with self.subTest(service=nom):
                postgres = environnement.get("POSTGRES_URL", "")
                mongo = environnement.get("MONGO_URL", "")
                self.assertEqual(bool(compte_pg), bool(postgres))
                self.assertEqual(bool(compte_mongo), bool(mongo))
                if compte_pg:
                    self.assertIn(f"//{compte_pg}:", postgres)
                if compte_mongo:
                    self.assertIn(f"//{compte_mongo}:", mongo)
                texte = json.dumps(environnement)
                interdits = ["POSTGRES_PASSWORD", "MONGO_ROOT", "svc_lecture"]
                if nom not in PORTE_L_API_METIER:
                    interdits += ["svc_app", "JWT_SECRET", "APP_DATABASE_URL"]
                for interdit in interdits:
                    self.assertNotIn(interdit, texte, "un service n'a ni le compte administrateur ni celui d'un autre")

    def test_le_service_qui_porte_l_api_metier_a_en_plus_le_compte_du_schema_app_et_le_secret_des_jetons(self):
        # Exception assumée (BE-03, point ouvert n° 1 des diagrammes C4) : seul ce service, et pas les autres.
        for nom in PORTE_L_API_METIER:
            environnement = self.services[nom]["environment"]
            with self.subTest(service=nom):
                self.assertIn("//svc_app:", environnement["APP_DATABASE_URL"])
                self.assertIn("${PG_PASSWORD_APP}", environnement["APP_DATABASE_URL"])
                self.assertEqual(environnement["JWT_SECRET"], "${JWT_SECRET:-}", "pas de secret en clair dans le fichier")
        for nom in COMPTES:
            if nom not in PORTE_L_API_METIER:
                self.assertNotIn("APP_DATABASE_URL", self.services[nom]["environment"])

    def test_les_services_recoivent_l_adresse_du_bus_et_leur_nom(self):
        for nom in COMPTES:
            environnement = self.services[nom]["environment"]
            self.assertEqual(environnement["KAFKA_BOOTSTRAP_SERVERS"], "kafka:9092")
            self.assertEqual(environnement["SERVICE_NAME"], nom)


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class OrdreDeDemarrage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.services = compose()["services"]

    def test_aucune_dependance_ne_repose_sur_un_simple_demarrage(self):
        for nom, service in self.services.items():
            for cible, condition in dependances(service).items():
                with self.subTest(service=nom, depend_de=cible):
                    self.assertIn(condition, {"service_healthy", "service_completed_successfully"})

    def test_une_tache_unique_est_attendue_par_sa_fin_et_un_service_par_sa_sonde(self):
        for nom, service in self.services.items():
            for cible, condition in dependances(service).items():
                with self.subTest(service=nom, depend_de=cible):
                    if cible in TACHES_UNIQUES:
                        self.assertEqual(condition, "service_completed_successfully")
                    else:
                        self.assertEqual(condition, "service_healthy")
                        self.assertTrue(a_une_sonde(self.services[cible], self.services),
                                        f"{cible} n'a pas de sonde de santé : l'attente ne finirait jamais")

    def test_l_ordre_attendu(self):
        attendu = {
            "kafka-init": {"kafka"},
            "collecte": {"mongo", "kafka-init"},
            "traitement": {"postgres", "mongo", "db-migrate", "kafka-init"},
            "alerte": {"postgres", "db-migrate", "kafka-init"},
            "reponse": {"mongo", "kafka-init"},
            "simulateur": {"collecte"},
            "passerelle": {"traitement", "alerte", "reponse"},
            "frontend": {"passerelle"},
        }
        for nom, cibles in attendu.items():
            with self.subTest(service=nom):
                self.assertEqual(set(dependances(self.services[nom])), cibles)

    def test_le_graphe_n_a_pas_de_cycle(self):
        for depart in self.services:
            pile, vus = list(dependances(self.services[depart])), set()
            while pile:
                courant = pile.pop()
                self.assertNotEqual(courant, depart, f"cycle autour de {depart}")
                if courant not in vus:
                    vus.add(courant)
                    pile.extend(dependances(self.services[courant]))

    def test_chaque_service_applicatif_est_sain_avant_ses_dependants(self):
        for nom in APPLICATIFS:
            self.assertTrue(a_une_sonde(self.services[nom], self.services), nom)

    def test_la_passerelle_attend_les_services_qu_elle_expose_pas_la_collecte(self):
        self.assertNotIn("collecte", dependances(self.services["passerelle"]))


class SujetsKafkaCreesAuDemarrage(unittest.TestCase):
    def sujets_du_script(self) -> dict[str, tuple[str, ...]]:
        texte = (RACINE / "infra" / "kafka" / "init-topics.sh").read_text(encoding="utf-8")
        return {nom: tuple(re.findall(r"--config (\S+)", reste))
                for nom, reste in re.findall(r"(?m)^creer (\S+)(.*)$", texte)}

    def test_le_script_cree_les_memes_sujets_que_dev_py_et_la_matrice_des_contrats(self):
        sujets = self.sujets_du_script()
        self.assertEqual(list(sujets), [t.name for t in dev.KAFKA_TOPICS])
        for topic in dev.KAFKA_TOPICS:
            self.assertEqual(sujets[topic.name], topic.configs)
        matrice = json.loads((RACINE / "contracts" / "topics.json").read_text(encoding="utf-8"))["topics"]
        self.assertEqual(list(sujets), list(matrice))

    def test_le_script_utilise_le_meme_nombre_de_partitions_que_dev_py(self):
        texte = (RACINE / "infra" / "kafka" / "init-topics.sh").read_text(encoding="utf-8")
        self.assertIn(f"--partitions {dev.KAFKA_PARTITIONS}", texte)
        self.assertIn("--if-not-exists", texte)  # rejouable sans erreur
        self.assertIn("set -eu", texte)

    def test_le_script_a_des_fins_de_ligne_unix(self):
        # un CRLF (poste Windows) ferait échouer le script dans le conteneur Linux
        self.assertNotIn(b"\r", (RACINE / "infra" / "kafka" / "init-topics.sh").read_bytes())
        self.assertNotIn(b"\r", (RACINE / "gateway" / "nginx.conf").read_bytes())

    @unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
    def test_la_tache_attend_le_broker_et_monte_le_script_en_lecture_seule(self):
        tache = compose()["services"]["kafka-init"]
        self.assertEqual(tache["restart"], "no")
        self.assertIn("./infra/kafka/init-topics.sh:/init-topics.sh:ro", tache["volumes"])
        self.assertEqual(dependances(tache), {"kafka": "service_healthy"})


def emplacements(nginx: str) -> list[tuple[str, str, str]]:
    """(modificateur, motif, destination) de chaque `location` ; la destination est le service de proxy_pass,
    « 503 » ou « 404 » pour une réponse de la passerelle elle-même."""
    resultat = []
    for modificateur, motif, corps in re.findall(r"location (=|~|\^~)?\s*(\S+) \{(.*?)\n  \}", nginx, re.S):
        proxy = re.search(r"proxy_pass http://([a-z-]+):8000;", corps)
        retour = re.search(r"return (\d+)", corps)
        resultat.append((modificateur, motif, proxy.group(1) if proxy else retour.group(1)))
    return resultat


def route(chemin: str, table: list[tuple[str, str, str]]) -> str:
    """Destination de `chemin` selon les règles de nginx : exact, puis préfixe `^~`, puis expressions dans l'ordre,
    puis le plus long préfixe."""
    for modificateur, motif, destination in table:
        if modificateur == "=" and chemin == motif:
            return destination
    for modificateur, motif, destination in table:
        if modificateur == "^~" and chemin.startswith(motif):
            return destination
    for modificateur, motif, destination in table:
        if modificateur == "~" and re.search(motif, chemin):
            return destination
    prefixes = [(len(motif), destination) for modificateur, motif, destination in table
                if modificateur == "" and chemin.startswith(motif)]
    return max(prefixes)[1]


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class PasserelleRouteLesContrats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = emplacements((RACINE / "gateway" / "nginx.conf").read_text(encoding="utf-8"))

    def chemins(self, service: str) -> list[str]:
        doc = yaml.safe_load((RACINE / "contracts" / "openapi" / f"{service}.openapi.yaml").read_text(encoding="utf-8"))
        return [re.sub(r"{\w+}", "INT_01", c) for c in doc["paths"] if c != "/api/v1/health"]

    def test_chaque_chemin_de_chaque_service_va_vers_son_service(self):
        for service in ("traitement", "alerte", "reponse"):
            for chemin in self.chemins(service):
                with self.subTest(service=service, chemin=chemin):
                    self.assertEqual(route(chemin, self.table), service)

    def test_la_sonde_de_l_api_est_servie_par_le_traitement_en_attendant_l_api_metier(self):
        self.assertEqual(route("/api/v1/health", self.table), "traitement")

    def test_l_api_metier_est_servie_par_le_traitement_qui_porte_son_role(self):
        for chemin in self.chemins("api-metier"):
            with self.subTest(chemin=chemin):
                self.assertEqual(route(chemin, self.table), "traitement")

    def test_le_depot_des_mesures_n_est_pas_expose(self):
        for chemin in self.chemins("collecte"):
            with self.subTest(chemin=chemin):
                self.assertEqual(route(chemin, self.table), "404")

    def test_la_passerelle_a_sa_propre_sonde_et_refuse_le_reste(self):
        self.assertEqual(route("/health", self.table), "200")
        self.assertEqual(route("/n-importe-quoi", self.table), "404")
        self.assertEqual(route("/api/v1/inconnu", self.table), "404")

    def test_une_route_ne_deborde_pas_sur_un_nom_voisin(self):
        # « signals » ne doit pas capter « signalsfoo » ; « alerts » ne doit pas capter « alertsxyz »
        for chemin in ("/api/v1/signalsfoo", "/api/v1/alertsxyz", "/api/v1/indicatorsfoo"):
            self.assertEqual(route(chemin, self.table), "404", chemin)

    def test_le_flux_sse_n_est_pas_mis_en_tampon(self):
        nginx = (RACINE / "gateway" / "nginx.conf").read_text(encoding="utf-8")
        bloc = re.search(r"location = /api/v1/events/stream \{(.*?)\n  \}", nginx, re.S).group(1)
        self.assertIn("proxy_buffering off", bloc)

    def test_les_erreurs_de_la_passerelle_suivent_le_format_problem(self):
        nginx = (RACINE / "gateway" / "nginx.conf").read_text(encoding="utf-8")
        for code in re.findall(r'return (?:404|503) \'(\{.*?\})\';', nginx):
            corps = json.loads(code.replace("$correlation_id", "x"))
            self.assertEqual(set(corps), {"type", "title", "status", "code", "detail", "correlation_id"})
        doc = yaml.safe_load((RACINE / "contracts" / "openapi" / "common.yaml").read_text(encoding="utf-8"))
        codes = set(doc["components"]["schemas"]["Problem"]["properties"]["code"]["enum"])
        self.assertLessEqual(set(re.findall(r'"code":"([A-Z_]+)"', nginx)), codes)

    def test_la_correlation_est_transmise_et_renvoyee(self):
        nginx = (RACINE / "gateway" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("proxy_set_header X-Correlation-ID $correlation_id;", nginx)
        self.assertIn("add_header X-Correlation-ID $correlation_id always;", nginx)

    def test_le_frontend_passe_par_la_passerelle(self):
        self.assertIn("proxy_pass http://passerelle:8000;", (RACINE / "frontend" / "nginx.conf").read_text(encoding="utf-8"))
        passerelle = compose()["services"]["passerelle"]
        self.assertIn("./gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro", passerelle["volumes"])


class Simulateur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        specification = importlib.util.spec_from_file_location("simulateur_app", RACINE / "simulator" / "app.py")
        cls.app = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(cls.app)

    def requete(self, chemin: str) -> tuple[int, dict]:
        serveur = self.app.make_server(0, "127.0.0.1")
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        self.addCleanup(serveur.server_close)
        self.addCleanup(serveur.shutdown)
        connexion = http.client.HTTPConnection("127.0.0.1", serveur.server_address[1], timeout=5)
        connexion.request("GET", chemin)
        reponse = connexion.getresponse()
        return reponse.status, json.loads(reponse.read())

    def test_la_sonde_repond_comme_celle_des_services(self):
        statut, corps = self.requete("/api/v1/health")
        self.assertEqual(statut, 200)
        self.assertEqual(set(corps), {"status", "version", "revision", "environment"})
        self.assertEqual(corps["status"], "ok")
        self.assertTrue(all(isinstance(v, str) for v in corps.values()))

    def test_une_autre_route_est_introuvable(self):
        statut, corps = self.requete("/autre")
        self.assertEqual(statut, 404)
        self.assertIn("detail", corps)

    def test_l_image_tourne_sans_droits_et_a_une_sonde(self):
        dockerfile = (RACINE / "simulator" / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^USER appuser")
        self.assertRegex(dockerfile, r"(?s)\nHEALTHCHECK .*api/v1/health")  # la sonde tient sur deux lignes
        self.assertIn("apt-get upgrade", dockerfile)

    def test_le_squelette_dit_qu_il_n_est_pas_le_simulateur_final(self):
        self.assertIn("MS-07", (RACINE / "simulator" / "README.md").read_text(encoding="utf-8"))
        self.assertIn("MS-13", (RACINE / "gateway" / "README.md").read_text(encoding="utf-8"))


class SondesDeDevPy(unittest.TestCase):
    def serveur(self, statut: int, corps: str) -> str:
        class Gestionnaire(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(statut)
                self.end_headers()
                self.wfile.write(corps.encode("utf-8"))

            def log_message(self, *args):
                pass

        serveur = http.server.HTTPServer(("127.0.0.1", 0), Gestionnaire)
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        self.addCleanup(serveur.server_close)
        self.addCleanup(serveur.shutdown)
        return f"http://127.0.0.1:{serveur.server_address[1]}/"

    def test_ok_pour_un_statut_ok(self):
        ok, detail = dev.probe(self.serveur(200, '{"status":"ok","revision":"abc"}'))
        self.assertTrue(ok)
        self.assertIn("abc", detail)

    def test_ok_pour_une_page_html(self):
        self.assertEqual(dev.probe(self.serveur(200, "<html></html>")), (True, "HTTP 200"))

    def test_ko_pour_un_corps_qui_ne_dit_pas_ok(self):
        ok, detail = dev.probe(self.serveur(200, '{"status":"degraded"}'))
        self.assertFalse(ok)
        self.assertIn("degraded", detail)

    def test_ko_pour_une_erreur_http(self):
        self.assertEqual(dev.probe(self.serveur(503, "{}")), (False, "HTTP 503"))

    def test_ko_pour_un_port_ferme(self):
        ok, detail = dev.probe("http://127.0.0.1:1/", timeout=1)
        self.assertFalse(ok)
        self.assertIn("injoignable", detail)

    def test_chaque_conteneur_applicatif_a_sa_sonde_et_deux_chemins_traversent_la_chaine(self):
        noms = {c.name for c in dev.HEALTH_CHECKS}
        self.assertEqual(noms, APPLICATIFS)
        traversees = [c for c in dev.HEALTH_CHECKS if c.label]
        self.assertEqual([(c.name, c.path) for c in traversees],
                         [("passerelle", "/api/v1/health"), ("frontend", "/api/v1/health")])

    def test_les_ports_par_defaut_sont_ceux_de_compose(self):
        for check in dev.HEALTH_CHECKS:
            with self.subTest(sonde=check.name):
                self.assertEqual(check.default_port, VARIABLES_DE_PORT[check.port_variable])

    def test_le_port_vient_du_shell_puis_de_env_puis_du_defaut(self):
        check = next(c for c in dev.HEALTH_CHECKS if c.name == "collecte")
        self.assertEqual(dev.published_port(check, {}), 8001)
        self.assertEqual(dev.published_port(check, {"COLLECTE_PORT": "9001"}), 9001)
        with mock.patch.dict("os.environ", {"COLLECTE_PORT": "9002"}):
            self.assertEqual(dev.published_port(check, {"COLLECTE_PORT": "9001"}), 9002)

    def test_les_conteneurs_arretes_par_restore_sont_les_conteneurs_applicatifs(self):
        self.assertEqual(set(dev.APP_SERVICES), APPLICATIFS)


class CommandesUpDownHealth(unittest.TestCase):
    def lancer(self, commande, sondes=(0, 0)):
        appels = []

        def faux_compose(*args, **kwargs):
            appels.append(args)
            import subprocess
            return subprocess.CompletedProcess(args, 0)

        with mock.patch.object(dev, "require_env"), mock.patch.object(dev, "compose", side_effect=faux_compose), \
                mock.patch.object(dev, "check_health", return_value=(["  [OK] x"] * 9, sondes[1])) as sonde, \
                mock.patch("builtins.print") as affichage:
            code = commande(argparse.Namespace(wait=0))
        sortie = "\n".join(str(c.args[0]) for c in affichage.call_args_list)
        return code, appels, sonde, sortie

    def test_up_demarre_tout_puis_attend_les_sondes(self):
        code, appels, sonde, sortie = self.lancer(dev.cmd_up)
        self.assertEqual(code, 0)
        self.assertEqual(appels, [("up", "--build", "-d", "--remove-orphans")])
        sonde.assert_called_once_with(dev.HEALTH_WAIT_SECONDS)
        self.assertIn("Front-end : http://localhost:", sortie)

    def test_up_echoue_si_une_sonde_echoue(self):
        code, _, _, sortie = self.lancer(dev.cmd_up, sondes=(0, 2))
        self.assertEqual(code, 1)
        self.assertIn("2 sonde(s) en échec", sortie)
        self.assertNotIn("Front-end : http://localhost:", sortie)

    def test_down_supprime_les_conteneurs_sans_toucher_aux_donnees(self):
        code, appels, _, sortie = self.lancer(dev.cmd_down)
        self.assertEqual(code, 0)
        self.assertEqual(appels, [("down", "--remove-orphans")])
        self.assertNotIn("-v", appels[0])
        self.assertIn("données sont conservées", sortie)

    def test_health_fait_un_seul_essai_par_defaut_et_echoue_si_une_sonde_echoue(self):
        code, _, sonde, _ = self.lancer(dev.cmd_health, sondes=(0, 1))
        self.assertEqual(code, 1)
        sonde.assert_called_once_with(0)

    def test_la_commande_health_existe(self):
        args = dev.build_parser().parse_args(["health", "--wait", "30"])
        self.assertEqual((args.command, args.wait), ("health", 30))

    def test_le_makefile_a_les_raccourcis(self):
        makefile = (RACINE / "Makefile").read_text(encoding="utf-8")
        for cible in ("up", "down", "health"):
            self.assertRegex(makefile, rf"(?m)^{cible}:.*\n\t\$\(DEV\) {cible}$")


if __name__ == "__main__":
    unittest.main()
