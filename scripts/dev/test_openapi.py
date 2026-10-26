"""Contrôle du contrat OpenAPI v1 (issue BE-01).

Critère d'acceptation : le fichier OpenAPI se charge sans erreur. Ce test charge docs/02-specifications/openapi.yaml,
vérifie sa structure (références, identifiants d'opération, sécurité, format d'erreur) et sa concordance avec les
contrats d'événements de contracts/events/.

Dépendance : PyYAML (`pip install pyyaml`). Sans elle, les tests sont ignorés, pas en échec.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_openapi.py"   (Windows : py -3 ...)
"""
import json
import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dépend du poste
    yaml = None

RACINE = Path(__file__).resolve().parents[2]
CONTRAT = RACINE / "docs" / "02-specifications" / "openapi.yaml"
EVENEMENTS = RACINE / "contracts" / "events"
METHODES = {"get", "put", "post", "patch", "delete", "head", "options"}
ROLES = {"viewer", "operator", "admin"}
ROUTES_PUBLIQUES = {"getHealth", "login"}


def charger() -> dict:
    return yaml.safe_load(CONTRAT.read_text(encoding="utf-8"))


def operations(doc: dict):
    """(chemin, méthode, opération) pour chaque opération du contrat."""
    for chemin, item in doc["paths"].items():
        for methode, operation in item.items():
            if methode in METHODES:
                yield chemin, methode, operation


def references(noeud):
    """Toutes les valeurs de `$ref` présentes dans le contrat."""
    if isinstance(noeud, dict):
        for cle, valeur in noeud.items():
            if cle == "$ref" and isinstance(valeur, str):
                yield valeur
            else:
                yield from references(valeur)
    elif isinstance(noeud, list):
        for element in noeud:
            yield from references(element)


def resoudre(doc: dict, ref: str):
    noeud = doc
    for morceau in ref.removeprefix("#/").split("/"):
        noeud = noeud[morceau]
    return noeud


def enum_json(fichier: str, *chemin: str) -> list:
    noeud = json.loads((EVENEMENTS / fichier).read_text(encoding="utf-8"))
    for morceau in chemin:
        noeud = noeud[morceau]
    return noeud["enum"]


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class ContratOpenApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = charger()

    def test_le_fichier_se_charge_et_porte_la_bonne_version(self):
        self.assertTrue(str(self.doc["openapi"]).startswith("3.1."))
        for cle in ("info", "paths", "components", "servers", "tags", "security"):
            self.assertIn(cle, self.doc)
        self.assertTrue(self.doc["info"]["version"])

    def test_toutes_les_references_locales_se_resolvent(self):
        manquantes = []
        for ref in references(self.doc):
            self.assertTrue(ref.startswith("#/"), f"référence externe non prévue : {ref}")
            try:
                resoudre(self.doc, ref)
            except (KeyError, TypeError):
                manquantes.append(ref)
        self.assertEqual(manquantes, [])

    def test_tous_les_chemins_sont_sous_api_v1(self):
        hors_version = [c for c in self.doc["paths"] if not c.startswith("/api/v1/")]
        self.assertEqual(hors_version, [])

    def test_les_identifiants_d_operation_sont_uniques_et_en_camel_case(self):
        ids = [op["operationId"] for _, _, op in operations(self.doc)]
        self.assertEqual(len(ids), len(set(ids)), "operationId en double")
        for identifiant in ids:
            self.assertRegex(identifiant, r"^[a-z][A-Za-z0-9]*$")

    def test_chaque_operation_est_decrite(self):
        etiquettes = {t["name"] for t in self.doc["tags"]}
        for chemin, methode, op in operations(self.doc):
            with self.subTest(operation=f"{methode.upper()} {chemin}"):
                self.assertTrue(op.get("summary"))
                self.assertTrue(op.get("tags"))
                self.assertLessEqual(set(op["tags"]), etiquettes)
                self.assertTrue(op.get("responses"))

    def test_les_parametres_de_chemin_sont_declares(self):
        for chemin, item in self.doc["paths"].items():
            attendus = set(re.findall(r"{(\w+)}", chemin))
            for methode, op in item.items():
                if methode not in METHODES:
                    continue
                params = list(item.get("parameters", [])) + list(op.get("parameters", []))
                declares = set()
                for p in params:
                    p = resoudre(self.doc, p["$ref"]) if "$ref" in p else p
                    if p["in"] == "path":
                        declares.add(p["name"])
                        self.assertTrue(p["required"])
                with self.subTest(operation=f"{methode.upper()} {chemin}"):
                    self.assertEqual(declares, attendus)

    def test_seules_la_sonde_et_la_connexion_sont_publiques(self):
        publiques = {op["operationId"] for _, _, op in operations(self.doc) if op.get("security") == []}
        self.assertEqual(publiques, ROUTES_PUBLIQUES)

    def test_toute_route_protegee_declare_un_role_et_ses_refus(self):
        for chemin, methode, op in operations(self.doc):
            if op["operationId"] in ROUTES_PUBLIQUES:
                continue
            with self.subTest(operation=f"{methode.upper()} {chemin}"):
                self.assertIn(op.get("x-required-role"), ROLES)
                self.assertIn("401", op["responses"])
                if op["x-required-role"] != "viewer":
                    self.assertIn("403", op["responses"])

    def test_les_erreurs_ont_un_seul_format(self):
        for chemin, methode, op in operations(self.doc):
            for statut, reponse in op["responses"].items():
                if statut[0] not in "45":
                    continue
                reponse = resoudre(self.doc, reponse["$ref"]) if "$ref" in reponse else reponse
                with self.subTest(operation=f"{methode.upper()} {chemin}", statut=statut):
                    contenu = reponse["content"]
                    self.assertEqual(list(contenu), ["application/problem+json"])
                    self.assertEqual(contenu["application/problem+json"]["schema"], {"$ref": "#/components/schemas/Problem"})

    def test_les_listes_utilisent_la_pagination_commune(self):
        for nom, schema in self.doc["components"]["schemas"].items():
            if nom.endswith("Page"):
                with self.subTest(schema=nom):
                    self.assertIn({"$ref": "#/components/schemas/PageInfo"}, schema["allOf"])

    def test_les_codes_d_erreur_cites_existent(self):
        codes = set(self.doc["components"]["schemas"]["Problem"]["properties"]["code"]["enum"])
        cites = set(re.findall(r"code `([A-Z]+(?:_[A-Z]+)+)`", CONTRAT.read_text(encoding="utf-8")))
        self.assertTrue(cites, "aucun code d'erreur cité dans les descriptions")
        self.assertLessEqual(cites, codes)

    def test_les_enumerations_suivent_les_contrats_d_evenements(self):
        schemas = self.doc["components"]["schemas"]
        attendu = {
            "CongestionState": enum_json("common.schema.json", "$defs", "congestion_state"),
            "SourceType": enum_json("common.schema.json", "$defs", "provenance", "properties", "source_type"),
            "AlertState": enum_json("alert-event.schema.json", "$defs", "data", "properties", "state"),
            "AlertKind": enum_json("alert-event.schema.json", "$defs", "data", "properties", "kind"),
            "Severity": enum_json("alert-event.schema.json", "$defs", "data", "properties", "severity"),
            "AlertCause": enum_json("alert-event.schema.json", "$defs", "data", "properties", "cause"),
        }
        for nom, valeurs in attendu.items():
            with self.subTest(schema=nom):
                self.assertEqual(schemas[nom]["enum"], valeurs)
        taille = json.loads((EVENEMENTS / "traffic-indicator.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schemas["WindowSize"]["enum"], taille["$defs"]["data"]["properties"]["window_size_s"]["enum"])

    def test_l_indicateur_reprend_les_champs_obligatoires_de_l_evenement(self):
        evenement = json.loads((EVENEMENTS / "traffic-indicator.schema.json").read_text(encoding="utf-8"))
        champs = set(evenement["$defs"]["data"]["required"])
        indicateur = self.doc["components"]["schemas"]["Indicator"]
        self.assertLessEqual(champs, set(indicateur["required"]))
        self.assertLessEqual(champs, set(indicateur["properties"]))

    def test_l_alerte_reprend_les_champs_obligatoires_de_l_evenement(self):
        evenement = json.loads((EVENEMENTS / "alert-event.schema.json").read_text(encoding="utf-8"))
        champs = set(evenement["$defs"]["data"]["required"]) - {"previous_state"}
        alerte = self.doc["components"]["schemas"]["Alert"]
        self.assertLessEqual(champs, set(alerte["required"]))

    def test_aucun_secret_dans_le_contrat(self):
        texte = CONTRAT.read_text(encoding="utf-8")
        self.assertNotRegex(texte, r"eyJ[A-Za-z0-9_-]{20,}")
        self.assertNotRegex(texte, r"(?i)(secret|token)\s*[:=]\s*['\"][A-Za-z0-9+/]{16,}")


if __name__ == "__main__":
    unittest.main()
