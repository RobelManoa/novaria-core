"""Application citoyenne (CIT-04, ADR-030) : elle reste d'accord avec le contrat de l'API publique et avec la décision.

Les tests de l'application elle-même sont en Vitest (`dev.py citoyen test`). Ceux-ci vérifient, sans Node, ce qui doit rester vrai
entre l'application et le reste du dépôt : mêmes valeurs que le contrat, une seule route appelée, rien gardé sur l'appareil, des
captures sur écran de téléphone présentes. Lancement : python3 -m unittest discover -s scripts/dev -p "test_application_citoyenne.py".
"""

import re
import struct
import subprocess
import unittest
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[2]
APP = RACINE / "citizen"
SRC = APP / "src"
CONTRAT = yaml.safe_load((RACINE / "contracts" / "openapi" / "traitement.openapi.yaml").read_text(encoding="utf-8"))
SCHEMAS = CONTRAT["components"]["schemas"]
CONTRAT_ALERTES = yaml.safe_load((RACINE / "contracts" / "openapi" / "alerte.openapi.yaml").read_text(encoding="utf-8"))
SCHEMAS_ALERTES = CONTRAT_ALERTES["components"]["schemas"]
CAPTURES = RACINE / "docs" / "Capture d'ecran"


def lire(nom: str) -> str:
    return (SRC / nom).read_text(encoding="utf-8")


def valeurs_ts(texte: str, nom: str) -> list[str]:
    """Les chaînes d'un `export const NOM = [...] as const` ."""
    corps = re.search(rf"export const {nom} = \[(.*?)\] as const", texte, re.S).group(1)
    return re.findall(r'"([A-Z_]+)"', corps)


def cles_ts(texte: str, nom: str) -> set[str]:
    corps = re.search(rf"export const {nom}[^=]*= \{{(.*?)\n\}};", texte, re.S).group(1)
    return set(re.findall(r"^\s*([A-Z_]+):", corps, re.M))


class AccordAvecLeContrat(unittest.TestCase):
    def test_les_etats_et_les_cotes_sont_ceux_du_contrat(self):
        types = lire("types.ts")
        self.assertEqual(set(valeurs_ts(types, "STATES")), set(SCHEMAS["CongestionState"]["enum"]))
        self.assertEqual(set(valeurs_ts(types, "APPROACHES")), set(SCHEMAS["PublicSegmentState"]["properties"]["approach"]["enum"]))

    def test_chaque_etat_et_chaque_cote_a_son_libelle_en_francais(self):
        labels = lire("labels.ts")
        for nom, attendu in (("STATE_LABEL", SCHEMAS["CongestionState"]["enum"]), ("STATE_HELP", SCHEMAS["CongestionState"]["enum"]),
                             ("APPROACH_LABEL", SCHEMAS["PublicSegmentState"]["properties"]["approach"]["enum"])):
            with self.subTest(table=nom):
                self.assertEqual(cles_ts(labels, nom), set(attendu))

    def test_les_libelles_sont_ceux_de_l_adr_030(self):
        adr = (RACINE / "docs" / "01-architecture" / "adr" / "ADR-030-application-citoyenne-perimetre-et-acces.md").read_text(encoding="utf-8")
        for code, mot in (("FREE_FLOW", "Fluide"), ("SLOW", "Ralenti"), ("CONGESTED", "Congestionné")):
            self.assertIn(f"`{code}` → « {mot} »", adr)
            self.assertRegex(lire("labels.ts"), rf'{code}: "{mot}"')

    def test_les_champs_lus_sont_exactement_les_six_du_contrat(self):
        champs = re.search(r"const FIELDS = \[(.*?)\];", lire("api.ts"), re.S).group(1)
        self.assertEqual(set(re.findall(r'"(\w+)"', champs)), set(SCHEMAS["PublicSegmentState"]["properties"]))
        interface = re.search(r"export interface SegmentState \{(.*?)\n\}", lire("types.ts"), re.S).group(1)
        self.assertEqual(set(re.findall(r"^\s*(\w+):", interface, re.M)), set(SCHEMAS["PublicSegmentState"]["properties"]))

    def test_la_route_appelee_est_la_route_publique_du_contrat(self):
        chemin = re.search(r'CONGESTION_PATH = "([^"]+)"', lire("api.ts")).group(1)
        operation = CONTRAT["paths"][chemin]["get"]
        self.assertEqual(operation["security"], [], "publique : sans jeton")
        self.assertEqual(set(CONTRAT["paths"][chemin]), {"get"})


class AccordAvecLeContratDesAlertes(unittest.TestCase):
    """CIT-05 : l'application lit `GET /api/v1/public/alerts` et rien d'autre de ce contrat."""

    def test_la_route_appelee_est_la_route_publique_d_alertes_du_contrat(self):
        chemin = re.search(r'ALERTS_PATH = "([^"]+)"', lire("api.ts")).group(1)
        operation = CONTRAT_ALERTES["paths"][chemin]["get"]
        self.assertEqual(operation["security"], [], "publique : sans jeton")
        self.assertEqual(set(CONTRAT_ALERTES["paths"][chemin]) - {"parameters", "summary", "description"}, {"get"})

    def test_les_champs_lus_sont_exactement_les_six_du_contrat(self):
        champs = re.search(r"const ALERT_FIELDS = \[(.*?)\];", lire("api.ts"), re.S).group(1)
        attendus = set(SCHEMAS_ALERTES["PublicAlert"]["properties"])
        self.assertEqual(set(re.findall(r'"(\w+)"', champs)), attendus)
        interface = re.search(r"export interface PublicAlert \{(.*?)\n\}", lire("types.ts"), re.S).group(1)
        self.assertEqual(set(re.findall(r"^\s*(\w+):", interface, re.M)), attendus)

    def test_les_gravites_sont_celles_du_contrat_et_ont_un_libelle_et_une_aide(self):
        gravites = set(SCHEMAS_ALERTES["Severity"]["enum"])
        self.assertEqual(set(valeurs_ts(lire("types.ts"), "SEVERITIES")), gravites)
        for table in ("SEVERITY_LABEL", "SEVERITY_HELP"):
            with self.subTest(table=table):
                self.assertEqual(cles_ts(lire("labels.ts"), table), gravites)

    def test_aucun_champ_interne_d_alerte_n_est_lu_ni_affiche(self):
        for fichier in SRC.rglob("*.ts*"):
            texte = fichier.read_text(encoding="utf-8")
            for interdit in ("acknowledged_by", "episode_id", "rule_id", "classifier_version", "scenario_id"):
                self.assertNotIn(interdit, texte, f"{fichier.name} : champ interne `{interdit}` (ADR-030, section 4.4)")

    def test_le_suivi_est_en_memoire_seulement(self):
        texte = lire("useFollow.ts")
        self.assertNotRegex(texte, r"localStorage|sessionStorage|indexedDB|document\.cookie")
        self.assertIn("en mémoire seulement", texte)


class SecretsEtEnTetes(unittest.TestCase):
    """CIT-06 : rien de secret dans ce qui est livré au navigateur, et rien qui envoie ou reçoit un jeton d'équipe."""

    FICHIERS = [p for p in (list(SRC.rglob("*")) + [APP / "index.html", APP / "vite.config.ts"]) if p.is_file() and p.suffix in (".ts", ".tsx", ".html")]
    SECRETS = ("JWT_SECRET", "PG_PASSWORD", "POSTGRES_PASSWORD", "MONGO_ROOT", "SECRET_KEY", "API_KEY", "BEGIN PRIVATE KEY", "BEGIN RSA", "AKIA")

    def test_aucun_fichier_d_environnement_dans_l_application(self):
        self.assertEqual([p.name for p in APP.glob(".env*")], [], "un .env de l'application serait lu par Vite et recopié dans la version construite")
        ignore = (RACINE / ".gitignore").read_text(encoding="utf-8")
        self.assertRegex(ignore, r"(?m)^\.env", "le dépôt public ignore les fichiers .env")

    def test_le_code_ne_lit_aucune_variable_d_environnement_secrete(self):
        for fichier in self.FICHIERS:
            texte = fichier.read_text(encoding="utf-8")
            for utilise in re.findall(r"import\.meta\.env\.(\w+)", texte):
                self.assertTrue(utilise.startswith("VITE_") or utilise in ("MODE", "DEV", "PROD", "BASE_URL"), f"{fichier.name} : {utilise}")
            self.assertNotIn("process.env", texte, fichier.name)

    def test_aucun_nom_de_secret_du_depot_n_apparait_dans_le_code_ni_la_configuration(self):
        for fichier in self.FICHIERS:
            texte = fichier.read_text(encoding="utf-8")
            for secret in self.SECRETS:
                self.assertNotIn(secret, texte, f"{fichier.name} cite {secret}")

    def test_l_application_n_envoie_jamais_d_en_tete_d_authentification_ni_de_cookie(self):
        for fichier in SRC.rglob("*.ts*"):
            texte = fichier.read_text(encoding="utf-8")
            self.assertNotRegex(texte, r"(?i)authorization|bearer|set-cookie|document\.cookie", fichier.name)
        api = lire("api.ts")
        self.assertIn('credentials: "omit"', api)
        self.assertIn('headers: { Accept: "application/json" }', api)

    def test_la_version_construite_ne_contient_ni_secret_ni_jeton(self):
        dist = APP / "dist"
        if not dist.is_dir():
            self.skipTest("version non construite (dev.py citoyen build)")
        for fichier in dist.rglob("*"):
            if fichier.is_file() and fichier.suffix in (".js", ".css", ".html", ".map", ".json"):
                texte = fichier.read_text(encoding="utf-8", errors="ignore")
                for secret in (*self.SECRETS, "Bearer ", "Authorization"):
                    self.assertNotIn(secret, texte, f"{fichier.name} contient {secret}")

    def test_le_relais_de_developpement_ne_vise_que_la_passerelle_locale(self):
        config = (APP / "vite.config.ts").read_text(encoding="utf-8")
        cibles = re.findall(r"https?://[\w.:-]+", config)
        self.assertTrue(cibles and all(c.startswith(("http://localhost", "http://127.0.0.1")) for c in cibles), cibles)
        self.assertIn('host: "127.0.0.1"', config, "le serveur de développement n'écoute que sur la machine")


class Garde_fous(unittest.TestCase):
    SOURCES = [p for p in SRC.rglob("*") if p.suffix in (".ts", ".tsx")]

    def test_une_seule_adresse_d_api_dans_tout_le_code(self):
        trouvees = set()
        for fichier in self.SOURCES:
            trouvees |= set(re.findall(r"/api/[\w/.-]*", fichier.read_text(encoding="utf-8")))
        self.assertEqual(trouvees, {"/api/v1/public/congestion", "/api/v1/public/alerts"}, "les deux routes publiques de l'ADR-030, et aucune autre")

    def test_seul_api_ts_appelle_le_reseau(self):
        for fichier in self.SOURCES:
            texte = fichier.read_text(encoding="utf-8")
            self.assertEqual("fetch(" in texte, fichier.name == "api.ts", fichier.name)
            self.assertNotRegex(texte, r"XMLHttpRequest|WebSocket|EventSource|sendBeacon")

    def test_aucun_jeton_aucun_cookie_aucun_stockage(self):
        for fichier in self.SOURCES:
            texte = fichier.read_text(encoding="utf-8")
            for interdit in ("Authorization", "Bearer", "localStorage", "sessionStorage", "indexedDB", "document.cookie", "Set-Cookie"):
                self.assertNotIn(interdit, texte, f"{fichier.name} : {interdit}")
        self.assertIn('credentials: "omit"', lire("api.ts"))

    def test_aucun_html_brut_ni_evaluation_de_code(self):
        for fichier in self.SOURCES:
            self.assertNotRegex(fichier.read_text(encoding="utf-8"), r"dangerouslySetInnerHTML|innerHTML|eval\(|new Function")

    def test_aucun_secret_ni_adresse_interne_dans_l_application(self):
        for fichier in [*self.SOURCES, APP / "vite.config.ts", APP / "index.html"]:
            texte = fichier.read_text(encoding="utf-8")
            self.assertNotRegex(texte, r"(?i)password|secret|api[_-]?key|postgres|mongodb://|kafka")

    def test_le_relais_de_vite_ne_vise_que_la_passerelle_et_que_le_chemin_api(self):
        config = (APP / "vite.config.ts").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'"(/[a-z]+)": cible', config), ["/api", "/api"])
        self.assertIn("http://localhost:8000", config)
        self.assertIn('host: "127.0.0.1"', config)

    def test_l_interface_dit_toujours_que_les_donnees_sont_simulees(self):
        self.assertIn("Données simulées", lire("components/Notices.tsx"))
        self.assertIn("<SimulatedBanner />", lire("App.tsx"))


class Depot(unittest.TestCase):
    def test_les_dependances_et_les_constructions_ne_sont_pas_versionnees(self):
        for chemin in ("citizen/node_modules/x", "citizen/dist/x", "citizen/coverage/x"):
            code = subprocess.run(["git", "check-ignore", "-q", chemin], cwd=RACINE, check=False).returncode
            self.assertEqual(code, 0, f"{chemin} doit être ignoré par Git")

    def test_le_fichier_de_verrou_existe_pour_que_npm_ci_reproduise_les_versions(self):
        self.assertTrue((APP / "package-lock.json").is_file())

    def test_les_captures_sur_ecran_de_telephone_existent_et_sont_des_images_de_la_bonne_largeur(self):
        noms = sorted(CAPTURES.glob("CIT-04-*.png"))
        self.assertGreaterEqual(len(noms), 8)
        self.assertTrue(any("api-reelle" in n.name for n in noms), "au moins une capture de l'API réelle")
        for chemin in noms:
            octets = chemin.read_bytes()
            self.assertEqual(octets[:8], b"\x89PNG\r\n\x1a\n", chemin.name)
            largeur = struct.unpack(">I", octets[16:20])[0]
            self.assertIn(largeur, (780, 640), f"{chemin.name} : 390 ou 320 pixels de large, en double densité")

    def test_les_captures_fabriquees_le_disent_dans_leur_nom(self):
        for chemin in CAPTURES.glob("CIT-04-*.png"):
            self.assertTrue("api-reelle" in chemin.name or "reponse-fabriquee" in chemin.name, chemin.name)

    def test_le_document_de_preuve_existe(self):
        texte = (RACINE / "docs" / "08-exploitation" / "application-citoyenne.md").read_text(encoding="utf-8")
        for attendu in ("dev.py citoyen", "CIT-04-01", "WCAG", "non vérifié", "reponse-fabriquee", "5174"):
            self.assertIn(attendu, texte)


if __name__ == "__main__":
    unittest.main()
