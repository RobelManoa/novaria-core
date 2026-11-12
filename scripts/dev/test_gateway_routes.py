"""MS-13 : les routes et les rôles de la passerelle viennent des contrats OpenAPI, et la configuration ne laisse
aucune route sans contrôle. Tests sans Docker (la passerelle réelle est éprouvée par gateway/tests/test_gateway.py).

Lancer :  python -m unittest discover -s scripts/dev -p "test_gateway_routes.py"
"""

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

RACINE = Path(__file__).resolve().parents[2]
GATEWAY = RACINE / "gateway"
CONTRATS = RACINE / "contracts" / "openapi"
VERBES = ("get", "post", "patch", "put", "delete")


def charger_generateur():
    specification = importlib.util.spec_from_file_location("gateway_routes", RACINE / "scripts" / "dev" / "gateway_routes.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules["gateway_routes"] = module
    specification.loader.exec_module(module)
    return module


def lire(nom: str) -> str:
    return (GATEWAY / nom).read_text(encoding="utf-8")


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class RoutesGenerees(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generateur = charger_generateur()
        cls.routes = json.loads(lire("routes.json"))

    def test_les_fichiers_generes_sont_ceux_que_le_script_produit(self):
        for chemin, contenu in self.generateur.produire().items():
            with self.subTest(fichier=chemin.name):
                self.assertEqual(chemin.read_bytes().decode("utf-8"), contenu,
                                 "relancer : python scripts/dev/gateway_routes.py")

    def test_chaque_operation_protegee_des_contrats_a_son_role_et_chaque_route_publique_est_declaree_publique(self):
        attendu = {}
        for fichier in CONTRATS.glob("*.openapi.yaml"):
            if fichier.name.startswith("collecte"):
                continue  # dépôt des mesures : interne, absent de la passerelle
            doc = yaml.safe_load(fichier.read_text(encoding="utf-8"))
            for chemin, item in doc["paths"].items():
                for verbe in VERBES:
                    operation = item.get(verbe)
                    if operation is not None:
                        role = None if operation.get("security") == [] else operation["x-required-role"]
                        attendu[(verbe.upper(), self.generateur.motif(chemin))] = role
        table = {(r["method"], r["pattern"]): r["role"] for r in self.routes}
        self.assertEqual(table, attendu)
        self.assertGreaterEqual(len([r for r in table.values() if r]), 20)

    def test_les_routes_publiques_sont_la_sonde_et_la_connexion_et_rien_d_autre(self):
        publiques = {(r["method"], r["pattern"]) for r in self.routes if r["role"] is None}
        self.assertEqual(publiques, {("GET", "^/api/v1/health$"), ("POST", "^/api/v1/auth/login$")})

    def test_les_roles_sont_ceux_des_services(self):
        roles = {r["role"] for r in self.routes} - {None}
        self.assertEqual(roles, {"viewer", "operator", "admin"})
        auth = (RACINE / "services" / "alerte" / "app" / "core" / "auth.py").read_text(encoding="utf-8")
        for role in roles:
            self.assertIn(f'"{role}"', auth)
        self.assertIn('ROLES = { viewer: 0, operator: 1, admin: 2 }', lire("auth.js"))  # même ordre que LEVEL des services

    def test_le_depot_des_mesures_n_a_aucune_route(self):
        self.assertFalse([r for r in self.routes if "measurements" in r["pattern"]])
        self.assertNotIn("/api/v1/measurements", lire("routes.conf").replace("^~ /api/v1/measurements", ""))

    def test_les_motifs_ne_debordent_pas(self):
        motif = re.compile(self.generateur.motif("/api/v1/alerts/{alert_id}/resolve"))
        self.assertTrue(motif.search("/api/v1/alerts/INT_01/resolve"))
        for faux in ("/api/v1/alerts/resolve", "/api/v1/alerts/a/b/resolve", "/api/v1/alerts/x/resolvex",
                     "/x/api/v1/alerts/x/resolve", "/api/v1/alerts//resolve"):
            self.assertFalse(motif.search(faux), faux)

    def test_chaque_location_est_protegee_ou_declaree_publique_et_une_seule_fois(self):
        routes = lire("routes.conf")
        blocs = re.findall(r"  location (?:=|~) \S+ \{\n(.*?)\n  \}\n", routes, re.S)
        self.assertGreaterEqual(len(blocs), 20)
        publics = 0
        for bloc in blocs:
            inclus = re.findall(r"include /etc/nginx/gateway/(protected|public)\.conf;", bloc)
            self.assertEqual(len(inclus), 1, bloc)
            self.assertEqual(len(re.findall(r"proxy_pass http://(traitement|alerte|reponse):8000;", bloc)), 1, bloc)
            self.assertIn("if ($request_method !~", bloc)  # méthodes du contrat seulement : le reste est un 405
            publics += inclus[0] == "public"
        self.assertEqual(publics, 2)  # la sonde et la connexion

    def test_aucun_proxy_pass_hors_des_routes_generees(self):
        self.assertNotIn("proxy_pass", lire("nginx.conf"))


class ConfigurationDeLaPasserelle(unittest.TestCase):
    def test_la_cle_vient_de_l_environnement_et_rien_n_est_ecrit_dans_le_dossier(self):
        nginx = lire("nginx.conf")
        self.assertIn("env JWT_SECRET;", nginx)
        for fichier in GATEWAY.iterdir():
            if fichier.is_file() and fichier.suffix in {".conf", ".js", ".json", ".md", ".mjs", ".py"}:
                texte = fichier.read_text(encoding="utf-8")
                self.assertNotRegex(texte, r"JWT_SECRET\s*[:=]\s*['\"][^'\"$]{8,}", fichier.name)
                self.assertNotRegex(texte, r"eyJ[A-Za-z0-9_-]{10,}\.eyJ", fichier.name)  # aucun jeton recopié
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("JWT_SECRET: ${JWT_SECRET:-}", compose)

    def test_le_journal_d_acces_ne_contient_ni_jeton_ni_chaine_de_requete(self):
        nginx = lire("nginx.conf")
        format_ = re.search(r"log_format passerelle (.*?);", nginx, re.S).group(1)
        for interdit in ("$http_authorization", "$request_uri", "$request ", "$query_string", "$args", "$http_cookie"):
            self.assertNotIn(interdit, format_)
        self.assertIn("$uri", format_)

    def test_le_cadre_de_securite_est_en_place(self):
        nginx = lire("nginx.conf")
        for attendu in ("server_tokens off;", "load_module modules/ngx_http_js_module.so;", "limit_req_zone", "limit_conn_zone",
                        "limit_req_status 429;", "real_ip_recursive off;", "client_max_body_size 1m;"):
            self.assertIn(attendu, nginx)
        self.assertRegex(nginx, r"location = /_auth \{\s+internal;")
        self.assertRegex(nginx, r"location = /_preflight \{\s+internal;")
        self.assertRegex(nginx, r"location / \{[^}]*return 404")  # tout le reste est refusé
        self.assertIn("if ($plain_path = 0)", nginx)  # chemins « simples » seulement : pas d'astuce d'encodage

    def test_l_authentification_est_branchee_sur_toute_route_protegee_et_le_filtre_d_en_tetes_partout(self):
        protegee = lire("protected.conf")
        self.assertIn("auth_request /_auth;", protegee)
        self.assertIn("rewrite ^ /_preflight last;", protegee)  # la pré-vérification CORS passe avant l'authentification
        self.assertIn("proxy_set_header X-User-Id $auth_user;", protegee)  # l'identité vérifiée écrase celle du client
        publique = lire("public.conf")
        self.assertNotIn("auth_request", publique)
        self.assertIn('proxy_set_header X-User-Id "";', publique)
        for nom in ("protected.conf", "public.conf"):
            self.assertIn("js_header_filter auth.headers;", lire(nom))
        nginx = lire("nginx.conf")
        # chaque `location` de nginx.conf qui répond lui-même porte le filtre (njs ne l'accepte qu'au niveau d'un location)
        for nom in ("@unauthorized", "@forbidden", "@too_many_requests", "@unavailable", "= /health", "^~ /api/v1/measurements", "/"):
            bloc = re.search(rf"    location {re.escape(nom)} \{{\n(.*?)\n    \}}", nginx, re.S)
            self.assertIsNotNone(bloc, nom)
            self.assertIn("js_header_filter auth.headers;", bloc.group(1), nom)

    def test_les_erreurs_de_la_passerelle_couvrent_l_authentification_et_la_limite(self):
        nginx = lire("nginx.conf")
        for ligne in ("error_page 401 = @unauthorized;", "error_page 403 = @forbidden;", "error_page 429 = @too_many_requests;",
                      "error_page 500 502 503 504 =503 @unavailable;"):
            self.assertIn(ligne, nginx)
        self.assertIn("add_header WWW-Authenticate Bearer always;", nginx)
        self.assertIn("add_header Retry-After $retry_after always;", nginx)

    def test_le_secret_est_traite_sans_etre_ecrit(self):
        js = lire("auth.js")
        self.assertNotIn("console.log", js)
        self.assertNotRegex(js, r"r\.(error|log|warn)\([^)]*(token|key|secret|Authorization)", )  # jamais dans un message
        self.assertIn('header.alg !== "HS256"', js)  # l'algorithme est fixé
        self.assertIn("exp <= now", js)


if __name__ == "__main__":
    unittest.main()
