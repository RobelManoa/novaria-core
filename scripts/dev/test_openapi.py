"""Contrôle des contrats OpenAPI par service (issues BE-01 et MS-03).

Critère de BE-01 : les fichiers OpenAPI se chargent sans erreur. Critère de MS-03 : un contrat par service, qui remplace le
contrat unique de BE-01. Ce test charge chaque contrat de contracts/openapi/, résout toutes les références (locales, vers
common.yaml et vers les schémas d'événements), vérifie la structure (identifiants d'opération, sécurité, format d'erreur,
pagination), la concordance avec contracts/events/ et le découpage : aucune opération de BE-01 perdue ni en double, aucun
composant partagé qui ne serve qu'un service, aucun composant orphelin.

Dépendance : PyYAML (`pip install pyyaml`). Sans elle, les tests sont ignorés, pas en échec.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_openapi.py"   (Windows : py -3 ...)
"""
import json
import os
import re
import unittest
from functools import cache
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dépend du poste
    yaml = None

RACINE = Path(__file__).resolve().parents[2]
OPENAPI = RACINE / "contracts" / "openapi"
EVENEMENTS = RACINE / "contracts" / "events"
COMMUN = "common.yaml"
SERVICES = ["api-metier", "traitement", "alerte", "reponse", "collecte"]
METHODES = {"get", "put", "post", "patch", "delete", "head", "options"}
ROLES = {"viewer", "operator", "admin"}
PUBLIQUES = {  # opérations sans jeton, par service
    "api-metier": {"getHealth", "login"},
    "traitement": {"getHealth"},
    "alerte": {"getHealth"},
    "reponse": {"getHealth"},
    "collecte": {"getHealth", "ingestMeasurement"},
}
# Opérations du contrat unique de BE-01 (25), figées ici : le découpage n'en perd aucune.
OPERATIONS_DE_BE_01 = {
    ("getHealth", "GET", "/api/v1/health"), ("login", "POST", "/api/v1/auth/login"),
    ("getCurrentUser", "GET", "/api/v1/auth/me"), ("listUsers", "GET", "/api/v1/users"),
    ("createUser", "POST", "/api/v1/users"), ("getUser", "GET", "/api/v1/users/{user_id}"),
    ("updateUser", "PATCH", "/api/v1/users/{user_id}"), ("listIntersections", "GET", "/api/v1/intersections"),
    ("getIntersection", "GET", "/api/v1/intersections/{intersection_id}"),
    ("listRoadSegments", "GET", "/api/v1/road-segments"), ("listIndicators", "GET", "/api/v1/indicators"),
    ("listLatestIndicators", "GET", "/api/v1/indicators/latest"),
    ("getIndicator", "GET", "/api/v1/indicators/{indicator_id}"), ("listAlerts", "GET", "/api/v1/alerts"),
    ("getAlert", "GET", "/api/v1/alerts/{alert_id}"),
    ("acknowledgeAlert", "POST", "/api/v1/alerts/{alert_id}/acknowledge"),
    ("resolveAlert", "POST", "/api/v1/alerts/{alert_id}/resolve"), ("listAlertRules", "GET", "/api/v1/alert-rules"),
    ("updateAlertRule", "PATCH", "/api/v1/alert-rules/{rule_id}"), ("listSignals", "GET", "/api/v1/signals"),
    ("getSignal", "GET", "/api/v1/signals/{intersection_id}"),
    ("listSignalCommands", "GET", "/api/v1/signals/{intersection_id}/commands"),
    ("sendSignalCommand", "POST", "/api/v1/signals/{intersection_id}/commands"),
    ("listForecasts", "GET", "/api/v1/forecasts"), ("streamEvents", "GET", "/api/v1/events/stream"),
}
GENRES = ("schemas", "parameters", "responses", "headers", "securitySchemes")


@cache
def charger(fichier: str) -> dict:
    chemin = OPENAPI / fichier
    texte = chemin.read_text(encoding="utf-8")
    return json.loads(texte) if fichier.endswith(".json") else yaml.safe_load(texte)


def contrat(service: str) -> dict:
    return charger(f"{service}.openapi.yaml")


def operations(doc: dict):
    """(chemin, méthode, opération) pour chaque opération du contrat."""
    for chemin, item in doc["paths"].items():
        for methode, operation in item.items():
            if methode in METHODES:
                yield chemin, methode, operation


def references(noeud):
    """Toutes les valeurs de `$ref` présentes dans un nœud."""
    if isinstance(noeud, dict):
        for cle, valeur in noeud.items():
            if cle == "$ref" and isinstance(valeur, str):
                yield valeur
            else:
                yield from references(valeur)
    elif isinstance(noeud, list):
        for element in noeud:
            yield from references(element)


def cible(fichier: str, ref: str):
    """(fichier cible, nœud) d'une référence ; KeyError si elle ne se résout pas."""
    nom, _, fragment = ref.partition("#")
    destination = fichier if not nom else os.path.normpath(nom).replace("\\", "/")
    noeud = charger(destination)
    for morceau in filter(None, fragment.split("/")):
        noeud = noeud[morceau]
    return destination, noeud


def composant(fichier: str, ref: str):
    """(fichier, genre, nom) si la référence vise un composant de contrat, sinon None."""
    m = re.fullmatch(r"(.*)#/components/(\w+)/(\w+)", ref)
    if not m:
        return None
    return (m.group(1) or fichier, m.group(2), m.group(3))


def composants_atteints(fichier: str, racines: list) -> set:
    """Composants (fichier, genre, nom) accessibles depuis des nœuds de départ, références transitives comprises."""
    vus: set = set()
    pile = [(fichier, ref) for noeud in racines for ref in references(noeud)]
    while pile:
        origine, ref = pile.pop()
        cle = composant(origine, ref)
        if cle is None:
            continue
        fichier_cible, genre, nom = cle
        if cle in vus:
            continue
        vus.add(cle)
        _, noeud = cible(fichier_cible, f"#/components/{genre}/{nom}")
        pile.extend((fichier_cible, r) for r in references(noeud))
    return vus


def enum_json(fichier: str, *chemin: str) -> list:
    noeud = json.loads((EVENEMENTS / fichier).read_text(encoding="utf-8"))
    for morceau in chemin:
        noeud = noeud[morceau]
    return noeud["enum"]


def schema(service: str, nom: str) -> dict:
    return contrat(service)["components"]["schemas"][nom]


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class ChaqueContrat(unittest.TestCase):
    def pour_chaque_service(self):
        for service in SERVICES:
            with self.subTest(service=service):
                yield service, f"{service}.openapi.yaml", contrat(service)

    def test_les_fichiers_se_chargent_et_portent_la_bonne_version(self):
        for service, fichier, doc in self.pour_chaque_service():
            self.assertTrue(str(doc["openapi"]).startswith("3.1."))
            for cle in ("info", "paths", "components", "tags"):
                self.assertIn(cle, doc)
            self.assertTrue(doc["info"]["version"])
            self.assertTrue(doc["info"]["title"].startswith("Novaria Core"))
        self.assertTrue(str(charger(COMMUN)["openapi"]).startswith("3.1."))

    def test_les_services_sont_ceux_de_l_adr_008(self):
        fichiers = sorted(p.name for p in OPENAPI.glob("*.openapi.yaml"))
        self.assertEqual(fichiers, sorted(f"{s}.openapi.yaml" for s in SERVICES))

    def test_toutes_les_references_se_resolvent(self):
        for service, fichier, doc in self.pour_chaque_service():
            manquantes = []
            for ref in references(doc):
                try:
                    cible(fichier, ref)
                except (KeyError, TypeError, FileNotFoundError):
                    manquantes.append(ref)
            self.assertEqual(manquantes, [])
        manquantes = []
        for ref in references(charger(COMMUN)):
            try:
                cible(COMMUN, ref)
            except (KeyError, TypeError, FileNotFoundError):
                manquantes.append(ref)
        self.assertEqual(manquantes, [])

    def test_les_references_externes_visent_common_ou_un_schema_d_evenement(self):
        for service, fichier, doc in self.pour_chaque_service():
            for ref in references(doc):
                nom = ref.partition("#")[0]
                self.assertTrue(nom in ("", COMMUN) or re.fullmatch(r"\.\./events/[a-z-]+\.schema\.json", nom), ref)

    def test_tous_les_chemins_sont_sous_api_v1(self):
        for service, fichier, doc in self.pour_chaque_service():
            self.assertEqual([c for c in doc["paths"] if not c.startswith("/api/v1/")], [])

    def test_les_identifiants_d_operation_sont_uniques_et_en_camel_case(self):
        for service, fichier, doc in self.pour_chaque_service():
            ids = [op["operationId"] for _, _, op in operations(doc)]
            self.assertEqual(len(ids), len(set(ids)), "operationId en double")
            for identifiant in ids:
                self.assertRegex(identifiant, r"^[a-z][A-Za-z0-9]*$")

    def test_chaque_operation_est_decrite(self):
        for service, fichier, doc in self.pour_chaque_service():
            etiquettes = {t["name"] for t in doc["tags"]}
            utilisees = set()
            for chemin, methode, op in operations(doc):
                with self.subTest(operation=f"{methode.upper()} {chemin}"):
                    self.assertTrue(op.get("summary"))
                    self.assertTrue(op.get("tags"))
                    self.assertLessEqual(set(op["tags"]), etiquettes)
                    self.assertTrue(op.get("responses"))
                utilisees |= set(op.get("tags", []))
            self.assertEqual(etiquettes, utilisees, "étiquette déclarée mais inutilisée, ou l'inverse")

    def test_les_parametres_de_chemin_sont_declares(self):
        for service, fichier, doc in self.pour_chaque_service():
            for chemin, item in doc["paths"].items():
                attendus = set(re.findall(r"{(\w+)}", chemin))
                for methode, op in item.items():
                    if methode not in METHODES:
                        continue
                    params = list(item.get("parameters", [])) + list(op.get("parameters", []))
                    declares = set()
                    for p in params:
                        p = cible(fichier, p["$ref"])[1] if "$ref" in p else p
                        if p["in"] == "path":
                            declares.add(p["name"])
                            self.assertTrue(p["required"])
                    with self.subTest(operation=f"{methode.upper()} {chemin}"):
                        self.assertEqual(declares, attendus)

    def test_seules_les_operations_prevues_sont_publiques(self):
        for service, fichier, doc in self.pour_chaque_service():
            publiques = {op["operationId"] for _, _, op in operations(doc) if op.get("security") == []}
            self.assertEqual(publiques, PUBLIQUES[service])

    def test_toute_route_protegee_declare_un_role_et_ses_refus(self):
        for service, fichier, doc in self.pour_chaque_service():
            for chemin, methode, op in operations(doc):
                if op["operationId"] in PUBLIQUES[service]:
                    continue
                with self.subTest(operation=f"{methode.upper()} {chemin}"):
                    self.assertIn(op.get("x-required-role"), ROLES)
                    self.assertIn("401", op["responses"])
                    if op["x-required-role"] != "viewer":
                        self.assertIn("403", op["responses"])

    def test_un_service_sans_route_protegee_ne_declare_pas_de_jeton(self):
        for service, fichier, doc in self.pour_chaque_service():
            protegees = [op for _, _, op in operations(doc) if op["operationId"] not in PUBLIQUES[service]]
            self.assertEqual(bool(protegees), "security" in doc, "jeton déclaré sans route protégée, ou l'inverse")
            self.assertEqual(bool(protegees), "securitySchemes" in doc["components"])

    def test_les_erreurs_ont_un_seul_format(self):
        probleme = cible(COMMUN, "#/components/schemas/Problem")[1]
        for service, fichier, doc in self.pour_chaque_service():
            for chemin, methode, op in operations(doc):
                for statut, reponse in op["responses"].items():
                    if statut[0] not in "45":
                        continue
                    origine = fichier
                    if "$ref" in reponse:
                        origine, reponse = cible(fichier, reponse["$ref"])
                    with self.subTest(operation=f"{methode.upper()} {chemin}", statut=statut):
                        contenu = reponse["content"]
                        self.assertEqual(list(contenu), ["application/problem+json"])
                        vise = contenu["application/problem+json"]["schema"]
                        self.assertIs(cible(origine, vise["$ref"])[1], probleme)

    def test_les_listes_utilisent_la_pagination_commune(self):
        info_page = cible(COMMUN, "#/components/schemas/PageInfo")[1]
        for service, fichier, doc in self.pour_chaque_service():
            for nom, definition in doc["components"].get("schemas", {}).items():
                if nom.endswith("Page"):
                    with self.subTest(schema=nom):
                        cibles = [cible(fichier, element["$ref"])[1] for element in definition["allOf"] if "$ref" in element]
                        self.assertIn(info_page, cibles)

    def test_les_codes_d_erreur_cites_existent(self):
        codes = set(charger(COMMUN)["components"]["schemas"]["Problem"]["properties"]["code"]["enum"])
        for service in SERVICES:
            texte = (OPENAPI / f"{service}.openapi.yaml").read_text(encoding="utf-8")
            cites = set(re.findall(r"code `([A-Z]+(?:_[A-Z]+)+)`", texte))
            self.assertLessEqual(cites, codes, service)

    def test_aucun_secret_dans_les_contrats(self):
        for chemin in OPENAPI.glob("*.yaml"):
            texte = chemin.read_text(encoding="utf-8")
            self.assertNotRegex(texte, r"eyJ[A-Za-z0-9_-]{20,}")
            self.assertNotRegex(texte, r"(?i)(secret|token)\s*[:=]\s*['\"][A-Za-z0-9+/]{16,}")


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class ConcordanceAvecLesEvenements(unittest.TestCase):
    def test_les_enumerations_suivent_les_contrats_d_evenements(self):
        attendu = {
            ("common.yaml", "SourceType"): enum_json("common.schema.json", "$defs", "provenance", "properties", "source_type"),
            ("traitement", "CongestionState"): enum_json("common.schema.json", "$defs", "congestion_state"),
            ("alerte", "AlertState"): enum_json("alert-event.schema.json", "$defs", "data", "properties", "state"),
            ("alerte", "AlertKind"): enum_json("alert-event.schema.json", "$defs", "data", "properties", "kind"),
            ("alerte", "Severity"): enum_json("alert-event.schema.json", "$defs", "data", "properties", "severity"),
            ("alerte", "AlertCause"): enum_json("alert-event.schema.json", "$defs", "data", "properties", "cause"),
        }
        for (proprietaire, nom), valeurs in attendu.items():
            with self.subTest(schema=nom):
                source = charger(COMMUN) if proprietaire == COMMUN else contrat(proprietaire)
                self.assertEqual(source["components"]["schemas"][nom]["enum"], valeurs)
        taille = json.loads((EVENEMENTS / "traffic-indicator.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema("traitement", "WindowSize")["enum"], taille["$defs"]["data"]["properties"]["window_size_s"]["enum"])

    def test_l_indicateur_reprend_les_champs_obligatoires_de_l_evenement(self):
        evenement = json.loads((EVENEMENTS / "traffic-indicator.schema.json").read_text(encoding="utf-8"))
        champs = set(evenement["$defs"]["data"]["required"])
        indicateur = schema("traitement", "Indicator")
        self.assertLessEqual(champs, set(indicateur["required"]))
        self.assertLessEqual(champs, set(indicateur["properties"]))

    def test_l_alerte_reprend_les_champs_obligatoires_de_l_evenement(self):
        evenement = json.loads((EVENEMENTS / "alert-event.schema.json").read_text(encoding="utf-8"))
        champs = set(evenement["$defs"]["data"]["required"]) - {"previous_state"}
        self.assertLessEqual(champs, set(schema("alerte", "Alert")["required"]))

    def test_la_collecte_recoit_l_evenement_complet_de_la_mesure(self):
        doc = contrat("collecte")
        operation = doc["paths"]["/api/v1/measurements"]["post"]
        corps = operation["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(corps, {"$ref": "../events/iot-measurement.schema.json"})
        self.assertTrue((OPENAPI / "../events/iot-measurement.schema.json").resolve().is_file())
        self.assertIn("202", operation["responses"])
        self.assertEqual(operation["responses"]["422"], {"$ref": "common.yaml#/components/responses/ValidationError"})
        self.assertIs(operation["x-internal"], True)

    def test_seule_la_collecte_a_une_operation_interne(self):
        for service in SERVICES:
            internes = {op["operationId"] for _, _, op in operations(contrat(service)) if op.get("x-internal")}
            self.assertEqual(internes, {"ingestMeasurement"} if service == "collecte" else set(), service)


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class DecoupageEnServices(unittest.TestCase):
    def test_aucune_operation_de_be_01_n_est_perdue_et_une_seule_est_ajoutee(self):
        presentes = {(op["operationId"], methode.upper(), chemin)
                     for service in SERVICES for chemin, methode, op in operations(contrat(service))}
        self.assertEqual(OPERATIONS_DE_BE_01 - presentes, set(), "opérations perdues")
        self.assertEqual(presentes - OPERATIONS_DE_BE_01, {("ingestMeasurement", "POST", "/api/v1/measurements")})

    def test_chaque_chemin_appartient_a_un_seul_service_sauf_la_sonde(self):
        proprietaires: dict[str, list[str]] = {}
        for service in SERVICES:
            for chemin in contrat(service)["paths"]:
                proprietaires.setdefault(chemin, []).append(service)
        for chemin, services in proprietaires.items():
            with self.subTest(chemin=chemin):
                self.assertEqual(services, SERVICES if chemin == "/api/v1/health" else services[:1])

    def test_la_sonde_est_identique_dans_chaque_service(self):
        sondes = [contrat(s)["paths"]["/api/v1/health"] for s in SERVICES]
        self.assertTrue(all(s["get"]["operationId"] == "getHealth" for s in sondes))
        self.assertEqual(len({json.dumps(s, sort_keys=True).replace("common.yaml", "") for s in sondes}), 1)

    def test_un_composant_commun_sert_au_moins_deux_services(self):
        utilises: dict = {}
        for service in SERVICES:
            doc = contrat(service)
            racines = [doc["paths"], doc["components"]]
            for cle in composants_atteints(f"{service}.openapi.yaml", racines):
                utilises.setdefault(cle, set()).add(service)
        common = charger(COMMUN)["components"]
        for genre in GENRES:
            for nom in common.get(genre, {}):
                with self.subTest(composant=f"{genre}/{nom}"):
                    self.assertGreaterEqual(len(utilises.get((COMMUN, genre, nom), set())), 2 if nom != "bearerAuth" else 1,
                                            "composant commun qui ne sert pas deux services : le ranger dans son service")

    def test_aucun_composant_n_est_defini_deux_fois(self):
        for service in SERVICES:
            local = contrat(service)["components"]
            for genre in GENRES:
                definis = {n for n, d in local.get(genre, {}).items() if "$ref" not in d}  # un $ref vers common n'est pas une copie
                en_double = definis & set(charger(COMMUN)["components"].get(genre, {}))
                self.assertEqual(en_double, set(), f"{service} redéfinit un composant commun")

    def test_aucun_composant_local_n_est_orphelin(self):
        for service in SERVICES:
            doc = contrat(service)
            atteints = composants_atteints(f"{service}.openapi.yaml", [doc["paths"], doc.get("security", [])])
            for genre in ("schemas", "parameters", "responses", "headers"):
                for nom in doc["components"].get(genre, {}):
                    with self.subTest(service=service, composant=f"{genre}/{nom}"):
                        self.assertIn((f"{service}.openapi.yaml", genre, nom), atteints)

    def test_les_composants_locaux_ne_servent_qu_a_leur_service(self):
        # un schéma local utilisé par un autre service passerait pour une dépendance cachée : il irait dans common.yaml
        for service in SERVICES:
            for autre in SERVICES:
                if autre == service:
                    continue
                texte = (OPENAPI / f"{autre}.openapi.yaml").read_text(encoding="utf-8")
                self.assertNotIn(f"{service}.openapi.yaml#", texte)


if __name__ == "__main__":
    unittest.main()
