"""Preuve de MS-13 : la VRAIE passerelle (nginx + njs, image réelle) devant trois services factices.

Critère : **un appel sans jeton valide est refusé pour tous les services.** Les trois services (`traitement`,
`alerte`, `reponse`) sont de petits nginx qui répondent par l'écho de ce qu'ils ont reçu : on voit ainsi ce que la
passerelle transmet (et ce qu'elle ne transmet pas). Chaque route des contrats OpenAPI (gateway/routes.json) est
essayée sans jeton, avec un jeton faux, expiré, d'un autre algorithme, d'un rôle trop faible, puis du bon rôle.

Lancer :  python -m unittest discover -s gateway/tests -p "test_gateway.py" -v      (Docker requis ; sinon ignoré)
          ou  make test-gateway

Les clés sont générées à l'exécution : aucune valeur secrète n'est écrite ici.
"""

import base64
import concurrent.futures
import hashlib
import hmac
import http.client
import itertools
import json
import re
import secrets
import shutil
import subprocess
import time
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
GATEWAY = RACINE / "gateway"
IMAGE = "nginxinc/nginx-unprivileged:1.30-alpine"
SERVICES = ("traitement", "alerte", "reponse")
ORIGINE = "http://localhost:8080"
AUTRE_ORIGINE = "http://evil.example"


def docker(*args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=check)


def docker_disponible() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return docker("info", check=False, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def b64(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).rstrip(b"=").decode()


def jeton(cle: str, role: str = "viewer", *, sub: str = "u-1", alg: str = "HS256", expire_dans: int = 600,
          emis_dans: int = 0, sans: tuple[str, ...] = (), signer: bool = True) -> str:
    """Un jeton HS256 comme celui de l'API métier (sub, role, iat, exp) ; les paramètres fabriquent les faux."""
    maintenant = int(time.time())
    revendications = {"sub": sub, "role": role, "iat": maintenant + emis_dans, "exp": maintenant + expire_dans}
    for nom in sans:
        revendications.pop(nom, None)
    entete = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    corps = b64(json.dumps(revendications).encode())
    if not signer:
        return f"{entete}.{corps}."
    signature = hmac.new(cle.encode(), f"{entete}.{corps}".encode(), hashlib.sha256).digest()
    return f"{entete}.{corps}.{b64(signature)}"


def exemple(chemin: str) -> str:
    """Un chemin concret d'un chemin de contrat : `{id}` devient une valeur plausible."""
    return re.sub(r"\{\w+\}", "INT_01", chemin)


def chemin_de(motif: str) -> str:
    """Un chemin concret d'un motif de routes.json (`^/api/v1/alerts/[^/]+$` -> `/api/v1/alerts/INT_01`)."""
    return motif.removeprefix("^").removesuffix("$").replace("[^/]+", "INT_01").replace("\\", "")


class Pile:
    """Trois services factices et une passerelle, dans un réseau Docker jetable."""

    def __init__(self) -> None:
        self.nom = f"novaria-gw-{secrets.token_hex(3)}"
        self.conteneurs: list[str] = []
        self.dossier = Path(__import__("tempfile").mkdtemp(prefix="novaria-gw-"))

    def demarrer_services(self) -> None:
        docker("network", "create", self.nom)
        for service in SERVICES:
            conf = self.dossier / f"{service}.conf"
            conf.write_text(
                "server {\n  listen 8000;\n  location / {\n    default_type application/json;\n"
                '    add_header Access-Control-Allow-Origin "*" always;\n'
                "    add_header X-Frame-Options SAMEORIGIN always;\n"
                "    add_header X-Powered-By factice always;\n"
                f"    return 200 '{{\"service\":\"{service}\",\"method\":\"$request_method\",\"uri\":\"$request_uri\","
                '"user":"$http_x_user_id","role":"$http_x_user_role","auth":"$http_authorization",'
                '"xff":"$http_x_forwarded_for","corr":"$http_x_correlation_id"}\';\n  }\n}\n',
                encoding="utf-8", newline="\n")
            nom = f"{self.nom}-{service}"
            docker("run", "-d", "--name", nom, "--network", self.nom, "--network-alias", service,
                   "-v", f"{conf.as_posix()}:/etc/nginx/conf.d/default.conf:ro", IMAGE)
            self.conteneurs.append(nom)

    def passerelle(self, *, cle: str | None, environnement: str = "local", origines: str = ORIGINE,
                   suffixe: str = "gw") -> tuple[str, int]:
        nom = f"{self.nom}-{suffixe}"
        env = ["-e", f"ENVIRONMENT={environnement}", "-e", f"CORS_ALLOWED_ORIGINS={origines}"]
        if cle is not None:
            env += ["-e", f"JWT_SECRET={cle}"]
        docker("run", "-d", "--name", nom, "--network", self.nom, "--network-alias", f"passerelle-{suffixe}", "-p", "127.0.0.1::8000", *env,
               "-v", f"{(GATEWAY / 'nginx.conf').as_posix()}:/etc/nginx/nginx.conf:ro",
               "-v", f"{GATEWAY.as_posix()}:/etc/nginx/gateway:ro", IMAGE)
        self.conteneurs.append(nom)
        port = int(docker("port", nom, "8000/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1])
        limite = time.monotonic() + 30
        while time.monotonic() < limite:
            try:
                connexion = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                connexion.request("GET", "/health")
                if connexion.getresponse().status == 200:
                    return nom, port
            except OSError:
                pass
            time.sleep(0.3)
        raise RuntimeError("passerelle injoignable :\n" + docker("logs", nom, check=False).stderr[-2000:])

    def journal(self, nom: str) -> str:
        sortie = docker("logs", nom, check=False)
        return sortie.stdout + sortie.stderr

    def supprimer(self) -> None:
        for nom in self.conteneurs:
            docker("rm", "-f", nom, check=False)
        docker("network", "rm", self.nom, check=False)
        shutil.rmtree(self.dossier, ignore_errors=True)


_ADRESSES = itertools.count(secrets.randbelow(60000))


def appeler(port: int, methode: str, chemin: str, *, jeton_: str | None = None, entetes: dict | None = None,
            corps: bytes | None = None, ip: str | None = None):
    """Un appel. Chaque appel vient, par défaut, d'une adresse à lui (X-Forwarded-For d'un relais du réseau privé) :
    la limitation de débit ne fausse pas les autres essais. Les essais de limite fixent `ip`."""
    n = next(_ADRESSES)
    en_tetes = {"X-Forwarded-For": ip or f"10.{n // 65025 % 250}.{n // 255 % 255}.{n % 254 + 1}", **(entetes or {})}
    if jeton_ is not None:
        en_tetes["Authorization"] = f"Bearer {jeton_}"
    if corps is not None:
        en_tetes.setdefault("Content-Type", "application/json")
    connexion = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connexion.request(methode, chemin, body=corps, headers=en_tetes)
    reponse = connexion.getresponse()
    donnees = reponse.read()
    connexion.close()
    try:
        contenu = json.loads(donnees) if donnees else None
    except ValueError:
        contenu = donnees.decode("utf-8", "replace")
    return reponse.status, {k.lower(): v for k, v in reponse.getheaders()}, contenu, reponse


@unittest.skipUnless(docker_disponible(), "Docker requis")
class PasserelleReelle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pile = Pile()
        cls.cle = secrets.token_urlsafe(48)
        cls.routes = json.loads((GATEWAY / "routes.json").read_text(encoding="utf-8"))
        try:
            cls.pile.demarrer_services()
            cls.nom, cls.port = cls.pile.passerelle(cle=cls.cle)
        except BaseException:
            cls.pile.supprimer()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.pile.supprimer()

    def appel(self, methode, chemin, **kwargs):
        return appeler(self.port, methode, chemin, **kwargs)

    def protegees(self):
        return [r for r in self.routes if r["role"] is not None]

    def publiques(self):
        return [r for r in self.routes if r["role"] is None]

    # ============================================================== le critère : sans jeton valide, refusé
    def test_une_route_protegee_de_chaque_service_est_refusee_sans_jeton_valide(self):
        """Critère d'acceptation : toutes les routes protégées, de tous les services, refusent un appel sans jeton valide."""
        servis = set()
        faux = {
            "aucun jeton": None,
            "jeton illisible": "pas-un-jeton",
            "trois morceaux vides": "..",
            "signé par une autre clé": jeton(secrets.token_urlsafe(48), "admin"),
            "expiré": jeton(self.cle, "admin", expire_dans=-10),
            "émis dans le futur": jeton(self.cle, "admin", emis_dans=3600),
            "algorithme none": jeton(self.cle, "admin", alg="none", signer=False),
            "algorithme HS384": jeton(self.cle, "admin", alg="HS384"),
            "sans sub": jeton(self.cle, "admin", sans=("sub",)),
            "sans role": jeton(self.cle, "admin", sans=("role",)),
            "sans exp": jeton(self.cle, "admin", sans=("exp",)),
            "sans iat": jeton(self.cle, "admin", sans=("iat",)),
            "rôle inconnu": jeton(self.cle, "root"),
        }
        for route in self.protegees():
            chemin = chemin_de(route["pattern"])
            for nom, valeur in faux.items():
                with self.subTest(route=f"{route['method']} {chemin}", jeton=nom):
                    statut, entetes, corps, _ = self.appel(route["method"], chemin, jeton_=valeur)
                    self.assertEqual(statut, 401, corps)
                    self.assertEqual(corps["code"], "UNAUTHENTICATED")
                    self.assertEqual(entetes["www-authenticate"], "Bearer")
                    self.assertEqual(entetes["content-type"], "application/problem+json")
                    self.assertEqual(set(corps), {"type", "title", "status", "code", "detail", "correlation_id"})
            servis.add(route["method"] + chemin)
        # les trois services sont bien dans la table essayée
        _, _, corps, _ = self.appel("GET", "/api/v1/alerts", jeton_=jeton(self.cle, "viewer"))
        self.assertEqual(corps["service"], "alerte")
        self.assertGreater(len(servis), 20)

    def test_aucun_autre_schema_d_authentification_n_est_accepte(self):
        valide = jeton(self.cle, "admin")
        for entete in (f"Basic {valide}", valide, f"Bearer{valide}", f"Bearer  {valide} extra", "Bearer"):
            with self.subTest(entete=entete[:12]):
                statut, *_ = self.appel("GET", "/api/v1/alerts", entetes={"Authorization": entete})
                self.assertEqual(statut, 401)

    def test_le_jeton_dans_l_adresse_ne_compte_pas(self):
        statut, *_ = self.appel("GET", f"/api/v1/alerts?access_token={jeton(self.cle, 'admin')}")
        self.assertEqual(statut, 401)

    def test_un_jeton_valide_passe_et_le_service_recoit_l_identite_verifiee(self):
        valide = jeton(self.cle, "operator", sub="u-42")
        statut, _, corps, _ = self.appel("GET", "/api/v1/signals", jeton_=valide)
        self.assertEqual(statut, 200)
        self.assertEqual((corps["service"], corps["user"], corps["role"]), ("reponse", "u-42", "operator"))
        self.assertEqual(corps["auth"], f"Bearer {valide}")  # le jeton est transmis : les services le contrôlent aussi

    def test_l_identite_ecrite_par_le_client_est_ecrasee(self):
        faux = {"X-User-Id": "pirate", "X-User-Role": "admin"}
        _, _, protegee, _ = self.appel("GET", "/api/v1/alerts", jeton_=jeton(self.cle, "viewer", sub="u-7"), entetes=faux)
        self.assertEqual((protegee["user"], protegee["role"]), ("u-7", "viewer"))
        _, _, publique, _ = self.appel("GET", "/api/v1/health", entetes=faux)
        self.assertEqual((publique["user"], publique["role"]), ("", ""))

    def jetons_de_l_api_metier(self) -> list[str]:
        """Trois jetons (viewer, operator, admin) émis comme l'API métier : le vrai `create_access_token` de
        services/traitement si son environnement le permet, sinon PyJWT avec la même charge utile (dates en
        `datetime`, comme `create_access_token`)."""
        def interpreteur(service: str):
            return next((p for p in (RACINE / "services" / service / ".venv" / "Scripts" / "python.exe",
                                     RACINE / "services" / service / ".venv" / "bin" / "python") if p.exists()), None)
        vrai = ("import sys, uuid; sys.path.insert(0, 'services/traitement'); "
                "from app.core.security import create_access_token; from app.models import Role; "
                "print(*[create_access_token(uuid.uuid4(), Role(r), secret=sys.argv[1], ttl_s=600).value for r in sys.argv[2:]])")
        copie = ("import sys, uuid, jwt; from datetime import UTC, datetime, timedelta; "
                 "now = datetime.now(UTC).replace(microsecond=0); "
                 "print(*[jwt.encode({'sub': str(uuid.uuid4()), 'role': r, 'iat': now, 'exp': now + timedelta(seconds=600)}, "
                 "sys.argv[1], algorithm='HS256') for r in sys.argv[2:]])")
        for service, code in (("traitement", vrai), ("reponse", copie), ("alerte", copie)):
            python = interpreteur(service)
            if python is None:
                continue
            sortie = subprocess.run([str(python), "-c", code, self.cle, "viewer", "operator", "admin"],
                                    capture_output=True, text=True, cwd=RACINE, encoding="utf-8")
            if sortie.returncode == 0 and len(sortie.stdout.split()) == 3:
                self.origine_des_jetons = "create_access_token (services/traitement)" if code is vrai else "PyJWT (même charge utile)"
                return sortie.stdout.split()
        self.skipTest("aucun environnement Python de services/ ne sait émettre un jeton")

    def test_un_jeton_emis_comme_le_fait_l_api_metier_est_accepte(self):
        """Compatibilité de format avec PyJWT et la charge utile de `create_access_token` (sub, role, iat, exp)."""
        viewer, operator, admin = self.jetons_de_l_api_metier()
        self.assertEqual(self.appel("GET", "/api/v1/alerts", jeton_=viewer)[0], 200)
        self.assertEqual(self.appel("POST", "/api/v1/alerts/INT_01/resolve", jeton_=viewer, corps=b"{}")[0], 403)
        self.assertEqual(self.appel("POST", "/api/v1/alerts/INT_01/resolve", jeton_=operator, corps=b"{}")[0], 200)
        self.assertEqual(self.appel("PATCH", "/api/v1/alert-rules/r1", jeton_=operator, corps=b"{}")[0], 403)
        self.assertEqual(self.appel("PATCH", "/api/v1/alert-rules/r1", jeton_=admin, corps=b"{}")[0], 200)

    def test_a_travers_le_nginx_du_front_end_les_en_tetes_restent_uniques_et_le_jeton_passe(self):
        """Le tableau de bord appelle l'API par le nginx du front-end (frontend/nginx.conf), qui parle à la passerelle."""
        conf = self.pile.dossier / "frontend.conf"
        texte = (RACINE / "frontend" / "nginx.conf").read_text(encoding="utf-8").replace("http://passerelle:8000", "http://passerelle-gw:8000")
        conf.write_text(texte, encoding="utf-8", newline="\n")
        nom = f"{self.pile.nom}-front"
        docker("run", "-d", "--name", nom, "--network", self.pile.nom, "-p", "127.0.0.1::8080",
               "-v", f"{conf.as_posix()}:/etc/nginx/conf.d/default.conf:ro", IMAGE)
        self.pile.conteneurs.append(nom)
        port = int(docker("port", nom, "8080/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1])
        limite = time.monotonic() + 15
        while time.monotonic() < limite:
            try:
                appeler(port, "GET", "/api/v1/health")
                break
            except OSError:
                time.sleep(0.3)
        statut, entetes, corps, reponse = appeler(port, "GET", "/api/v1/alerts", jeton_=jeton(self.cle, "viewer"))
        self.assertEqual((statut, corps["service"]), (200, "alerte"))
        for nom_ in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"):
            self.assertEqual(len(reponse.msg.get_all(nom_)), 1, nom_)  # un seul exemplaire, le front-end et la passerelle posent le même
        self.assertEqual(entetes["content-security-policy"], "default-src 'none'; frame-ancestors 'none'")
        self.assertEqual(appeler(port, "GET", "/api/v1/alerts")[0], 401)
        # l'adresse du navigateur arrive à la passerelle (X-Forwarded-For du front-end) : pas l'adresse du conteneur
        _, _, corps, _ = appeler(port, "GET", "/api/v1/alerts", jeton_=jeton(self.cle, "viewer"), ip="10.1.2.3")
        self.assertTrue(corps["xff"].startswith("172."), corps["xff"])  # la passerelle transmet l'adresse qu'elle a retenue
        statut, entetes, corps, _ = appeler(port, "GET", "/api/v1/events/stream", jeton_=jeton(self.cle, "viewer"))
        self.assertEqual((statut, entetes["cache-control"]), (200, "no-store"))

    # ============================================================== les rôles
    def test_chaque_role_obtient_ce_que_le_contrat_lui_donne(self):
        ordre = {"viewer": 0, "operator": 1, "admin": 2}
        for route in self.protegees():
            chemin = chemin_de(route["pattern"])
            for role in ordre:
                with self.subTest(route=f"{route['method']} {chemin}", role=role):
                    statut, _, corps, _ = self.appel(route["method"], chemin, jeton_=jeton(self.cle, role))
                    if ordre[role] < ordre[route["role"]]:
                        self.assertEqual(statut, 403, corps)
                        self.assertEqual(corps["code"], "FORBIDDEN")
                    else:
                        self.assertEqual(statut, 200, corps)  # arrivé au service factice

    def test_les_routes_publiques_n_exigent_pas_de_jeton(self):
        chemins = {(r["method"], chemin_de(r["pattern"])) for r in self.publiques()}
        self.assertEqual(chemins, {("GET", "/api/v1/health"), ("POST", "/api/v1/auth/login")})
        for methode, chemin in chemins:
            statut, _, corps, _ = self.appel(methode, chemin, corps=b"{}" if methode == "POST" else None)
            self.assertEqual(statut, 200)
            self.assertEqual(corps["service"], "traitement")

    # ============================================================== routage et chemins
    def test_une_route_inconnue_une_methode_non_permise_et_le_depot_des_mesures(self):
        valide = jeton(self.cle, "admin")
        statut, _, corps, _ = self.appel("GET", "/api/v1/inconnu", jeton_=valide)
        self.assertEqual((statut, corps["code"]), (404, "NOT_FOUND"))
        statut, _, corps, _ = self.appel("GET", "/api/v1/measurements", jeton_=valide)
        self.assertEqual((statut, corps["code"]), (404, "NOT_FOUND"))
        statut, _, corps, _ = self.appel("POST", "/api/v1/measurements", jeton_=valide, corps=b"{}")
        self.assertEqual(statut, 404)
        statut, entetes, corps, _ = self.appel("DELETE", "/api/v1/alerts", jeton_=valide)
        self.assertEqual((statut, corps["code"], entetes["allow"]), (405, "METHOD_NOT_ALLOWED", "GET, OPTIONS"))
        for interne in ("/_auth", "/_preflight"):
            statut, *_ = self.appel("GET", interne, jeton_=valide)
            self.assertEqual(statut, 404, interne)  # les sous-requêtes internes ne sont pas joignables

    def test_les_astuces_de_chemin_sont_refusees_avant_toute_decision(self):
        valide = jeton(self.cle, "admin")
        for chemin in ("/api/v1/%61lerts", "/api/v1//alerts", "/api/v1/./alerts", "/api/v1/alerts/../users",
                       "/api/v1/alerts/%2e%2e/users", "/api/v1/users/..", "/api/v1/alerts%2Fx", "/api/v1/alerts;x"):
            with self.subTest(chemin=chemin):
                statut, _, corps, _ = self.appel("GET", chemin, jeton_=valide)
                self.assertEqual((statut, corps["code"]), (400, "VALIDATION_ERROR"))

    def test_chaque_route_va_vers_le_service_du_contrat(self):
        for route in self.routes:
            chemin = chemin_de(route["pattern"])
            attendu = "alerte" if "alert" in chemin or "events" in chemin else "reponse" if "signals" in chemin else "traitement"
            jeton_ = None if route["role"] is None else jeton(self.cle, "admin")
            statut, _, corps, _ = self.appel(route["method"], chemin, jeton_=jeton_,
                                             corps=b"{}" if route["method"] in ("POST", "PATCH") else None)
            with self.subTest(route=f"{route['method']} {chemin}"):
                self.assertEqual((statut, corps["service"]), (200, attendu))

    # ============================================================== en-têtes de sécurité
    def test_les_en_tetes_de_securite_sont_ceux_de_la_passerelle_sur_toutes_les_reponses(self):
        valide = jeton(self.cle, "viewer")
        cas = {
            "réponse d'un service": self.appel("GET", "/api/v1/alerts", jeton_=valide),
            "401": self.appel("GET", "/api/v1/alerts"),
            "403": self.appel("POST", "/api/v1/alerts/INT_01/resolve", jeton_=valide, corps=b"{}"),
            "404": self.appel("GET", "/api/v1/inconnu"),
            "405": self.appel("PUT", "/api/v1/alerts", jeton_=valide),
            "sonde": self.appel("GET", "/health"),
        }
        for nom, (_, entetes, _, reponse) in cas.items():
            with self.subTest(reponse=nom):
                self.assertEqual(entetes["x-content-type-options"], "nosniff")
                self.assertEqual(entetes["x-frame-options"], "DENY")  # pas SAMEORIGIN, que le service factice envoie
                self.assertEqual(entetes["referrer-policy"], "no-referrer")
                self.assertEqual(entetes["content-security-policy"], "default-src 'none'; frame-ancestors 'none'")
                self.assertIn("x-correlation-id", entetes)
                self.assertNotIn("x-powered-by", entetes)
                self.assertNotRegex(entetes.get("server", ""), r"\d")  # pas de version de nginx
                self.assertEqual(len(reponse.msg.get_all("X-Frame-Options")), 1)  # un seul exemplaire

    def test_l_authentification_et_le_flux_ne_sont_jamais_mis_en_cache(self):
        _, entetes, _, _ = self.appel("POST", "/api/v1/auth/login", corps=b"{}")
        self.assertEqual(entetes["cache-control"], "no-store")
        _, entetes, _, _ = self.appel("GET", "/api/v1/events/stream", jeton_=jeton(self.cle, "viewer"))
        self.assertEqual(entetes["cache-control"], "no-store")

    def test_hsts_n_est_pose_que_derriere_un_point_qui_parle_tls(self):
        _, entetes, _, _ = self.appel("GET", "/health")
        self.assertNotIn("strict-transport-security", entetes)
        _, entetes, _, _ = self.appel("GET", "/health", entetes={"X-Forwarded-Proto": "https"})
        self.assertIn("max-age", entetes["strict-transport-security"])

    # ============================================================== corrélation
    def test_la_correlation_sobre_est_reprise_et_une_valeur_dangereuse_est_remplacee(self):
        _, entetes, corps, _ = self.appel("GET", "/api/v1/alerts", jeton_=jeton(self.cle, "viewer"),
                                         entetes={"X-Correlation-ID": "trace-abc_123"})
        self.assertEqual((entetes["x-correlation-id"], corps["corr"]), ("trace-abc_123", "trace-abc_123"))
        for dangereux in ('x","code":"HACK', "a b", "é", "x" * 101, "x\ty"):
            statut, entetes, corps, _ = self.appel("GET", "/api/v1/alerts", entetes={"X-Correlation-ID": dangereux})
            with self.subTest(valeur=dangereux[:12]):
                self.assertEqual(statut, 401)
                self.assertEqual(corps["code"], "UNAUTHENTICATED")  # le JSON n'a pas été détourné
                self.assertNotEqual(corps["correlation_id"], dangereux)
                self.assertEqual(corps["correlation_id"], entetes["x-correlation-id"])

    # ============================================================== CORS
    def test_la_preverification_d_une_origine_autorisee_passe_sans_jeton(self):
        statut, entetes, _, _ = self.appel("OPTIONS", "/api/v1/alerts/INT_01/acknowledge", entetes={
            "Origin": ORIGINE, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(statut, 204)
        self.assertEqual(entetes["access-control-allow-origin"], ORIGINE)
        self.assertIn("POST", entetes["access-control-allow-methods"])
        self.assertIn("Authorization", entetes["access-control-allow-headers"])
        self.assertEqual(entetes["access-control-max-age"], "600")
        self.assertEqual(entetes["vary"], "Origin")
        self.assertNotIn("access-control-allow-credentials", entetes)  # jamais de cookie

    def test_la_preverification_d_une_origine_inconnue_est_refusee(self):
        for origine in (AUTRE_ORIGINE, "null", "http://localhost:8080.evil.example", "*"):
            with self.subTest(origine=origine):
                statut, entetes, _, _ = self.appel("OPTIONS", "/api/v1/alerts", entetes={"Origin": origine})
                self.assertEqual(statut, 403)
                self.assertNotIn("access-control-allow-origin", entetes)

    def test_une_reponse_a_une_origine_autorisee_est_lisible_meme_en_erreur(self):
        valide = jeton(self.cle, "viewer")
        for chemin, jeton_, statut_attendu in (("/api/v1/alerts", valide, 200), ("/api/v1/alerts", None, 401),
                                               ("/api/v1/inconnu", None, 404)):
            statut, entetes, _, _ = self.appel("GET", chemin, jeton_=jeton_, entetes={"Origin": ORIGINE})
            with self.subTest(statut=statut_attendu):
                self.assertEqual(statut, statut_attendu)
                self.assertEqual(entetes["access-control-allow-origin"], ORIGINE)  # pas le « * » du service factice
                self.assertIn("X-Correlation-ID", entetes["access-control-expose-headers"])
        _, entetes, _, _ = self.appel("GET", "/api/v1/alerts", jeton_=valide, entetes={"Origin": AUTRE_ORIGINE})
        self.assertNotIn("access-control-allow-origin", entetes)  # le « * » du service factice est effacé
        _, entetes, _, _ = self.appel("GET", "/api/v1/alerts", jeton_=valide)
        self.assertNotIn("access-control-allow-origin", entetes)

    # ============================================================== limitation de débit
    def test_un_client_qui_martele_est_limite_en_429_au_format_problem(self):
        def une_fois(_):
            return self.appel("GET", "/api/v1/alerts", ip="10.9.9.9")

        # 200 appels en parallèle depuis la même adresse : bien plus que 20 par seconde plus la rafale de 40.
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            reponses = list(pool.map(une_fois, range(200)))
        statuts = [r[0] for r in reponses]
        dernier = next((r[1], r[2]) for r in reponses if r[0] == 429)
        self.assertIn(429, statuts)
        self.assertIn(401, statuts)  # les premiers passent la limite (et sont refusés par l'authentification)
        entetes, corps = dernier
        self.assertEqual(corps["code"], "RATE_LIMITED")
        self.assertEqual(entetes["retry-after"], "1")
        self.assertEqual(entetes["content-type"], "application/problem+json")
        time.sleep(2)
        self.assertEqual(self.appel("GET", "/api/v1/alerts", ip="10.9.9.9")[0], 401)  # la limite se desserre

    def test_la_connexion_a_sa_propre_limite_plus_stricte(self):
        statuts = [self.appel("POST", "/api/v1/auth/login", corps=b"{}", ip="10.9.9.10")[0] for _ in range(20)]
        self.assertEqual(statuts[:6], [200] * 6)  # 1 par 6 s + rafale de 5
        self.assertIn(429, statuts)
        _, entetes, corps, _ = self.appel("POST", "/api/v1/auth/login", corps=b"{}", ip="10.9.9.10")
        self.assertEqual((corps["code"], entetes["retry-after"]), ("RATE_LIMITED", "6"))

    # ============================================================== secrets
    def test_aucun_jeton_ni_cle_dans_les_journaux_de_la_passerelle(self):
        secret_jeton = jeton(self.cle, "admin", sub="u-secret")
        self.appel("GET", "/api/v1/alerts", jeton_=secret_jeton)
        self.appel("GET", f"/api/v1/alerts?access_token={secret_jeton}")
        self.appel("GET", "/api/v1/alerts", jeton_=jeton(self.cle, "admin", expire_dans=-5))
        journal = self.pile.journal(self.nom)
        self.assertIn('"GET /api/v1/alerts"', journal)  # le journal d'accès écrit bien quelque chose
        self.assertNotIn(self.cle, journal)
        self.assertNotIn(secret_jeton, journal)
        self.assertNotIn(secret_jeton.split(".")[1], journal)  # ni le corps du jeton
        self.assertNotIn("access_token", journal)  # ni la chaîne de requête

    def test_la_configuration_ne_contient_aucun_secret_et_ne_lit_que_l_environnement(self):
        for fichier in GATEWAY.iterdir():
            if fichier.is_file() and fichier.suffix in {".conf", ".js", ".json", ".md"}:
                self.assertNotIn(self.cle, fichier.read_text(encoding="utf-8"), fichier.name)
        nginx = (GATEWAY / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("env JWT_SECRET;", nginx)
        self.assertNotRegex(nginx, r"JWT_SECRET\s*=")


@unittest.skipUnless(docker_disponible(), "Docker requis")
class PasserelleMalConfiguree(unittest.TestCase):
    """Sans clé utilisable, la passerelle refuse tout ce qui est protégé : jamais un accès accordé par défaut."""

    @classmethod
    def setUpClass(cls):
        cls.pile = Pile()
        try:
            cls.pile.demarrer_services()
        except BaseException:
            cls.pile.supprimer()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.pile.supprimer()

    def verifier(self, **kwargs):
        cle = kwargs.get("cle") or secrets.token_urlsafe(48)
        _, port = self.pile.passerelle(suffixe=secrets.token_hex(2), **kwargs)
        for role in ("viewer", "admin"):
            statut, _, corps, _ = appeler(port, "GET", "/api/v1/alerts", jeton_=jeton(cle, role))
            self.assertEqual((statut, corps["code"]), (503, "UPSTREAM_UNAVAILABLE"), role)
        statut, *_ = appeler(port, "GET", "/api/v1/alerts")
        self.assertEqual(statut, 503)  # même sans jeton : rien ne passe
        self.assertEqual(appeler(port, "GET", "/health")[0], 200)  # la sonde de la passerelle répond
        self.assertEqual(appeler(port, "GET", "/api/v1/health")[0], 200)  # les routes publiques aussi

    def test_sans_cle(self):
        self.verifier(cle=None)

    def test_avec_une_cle_trop_courte(self):
        self.verifier(cle="trop-courte")

    def test_avec_la_valeur_d_exemple_hors_local(self):
        self.verifier(cle="change-me-local-" + secrets.token_urlsafe(30), environnement="production")

    def test_la_valeur_d_exemple_est_tolérée_en_local(self):
        cle = "change-me-local-" + secrets.token_urlsafe(30)
        _, port = self.pile.passerelle(cle=cle, suffixe="ex")
        self.assertEqual(appeler(port, "GET", "/api/v1/alerts", jeton_=jeton(cle, "viewer"))[0], 200)

    def test_sans_origine_configuree_aucun_en_tete_cors(self):
        cle = secrets.token_urlsafe(48)
        _, port = self.pile.passerelle(cle=cle, origines="", suffixe="nocors")
        statut, entetes, _, _ = appeler(port, "OPTIONS", "/api/v1/alerts", entetes={"Origin": ORIGINE})
        self.assertEqual(statut, 403)
        _, entetes, _, _ = appeler(port, "GET", "/api/v1/alerts", jeton_=jeton(cle, "viewer"), entetes={"Origin": ORIGINE})
        self.assertNotIn("access-control-allow-origin", entetes)
        self.assertNotIn("vary", entetes)


if __name__ == "__main__":
    unittest.main()
