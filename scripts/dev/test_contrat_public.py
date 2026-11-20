"""Contrat de l'API citoyenne (CIT-02, ADR-030) : champs exposés, aucune donnée interne, aucune écriture.

Le critère : « le contrat est versionné, la matrice d'accès le couvre et aucun champ interne n'est exposé. »
Ce test lit les deux routes publiques dans `contracts/openapi/` et les compare à ce que l'ADR-030 a décidé : la liste blanche des
champs (section 4.4) est lue **dans l'ADR**, pas recopiée ici, pour qu'un désaccord entre la décision et le contrat échoue.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_contrat_public.py"  (Windows : py -3 ...).
"""

import json
import re
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

RACINE = Path(__file__).resolve().parents[2]
CONTRATS = RACINE / "contracts" / "openapi"
ADR = RACINE / "docs" / "01-architecture" / "adr" / "ADR-030-application-citoyenne-perimetre-et-acces.md"
ESPACE = "/api/v1/public/"
ROUTES = {"/api/v1/public/congestion": ("traitement", "getPublicCongestion", "PublicCongestionList", "PublicSegmentState"),
          "/api/v1/public/alerts": ("alerte", "getPublicAlerts", "PublicAlertList", "PublicAlert")}
# Ce que l'ADR-030 (section 4.4) interdit : aucun de ces noms ne doit apparaître dans un schéma public.
INTERDITS = (
    "sensor_id", "vehicle_count", "flow_veh_per_min", "average_speed_kmh", "speed_ratio", "sample_count", "expected_sample_count",
    "occupancy", "queue_length", "classifier_version", "provenance", "run_id", "scenario_id", "seed", "source_type",
    "acknowledged_by", "acknowledged_at", "notified_at", "cause", "rule_id", "episode_id", "resolution", "resolved_at",
    "kind", "history", "from_state", "to_state", "intersection_command", "plan", "phase", "password", "token", "email",
)
# Seuls composants que les schémas publics peuvent référencer : des types simples, jamais un schéma interne (Alert, Indicator…).
REFERENCES_PERMISES = {
    "common.yaml#/components/schemas/RoadSegmentId", "common.yaml#/components/schemas/IntersectionId",
    "common.yaml#/components/schemas/UtcDateTime", "#/components/schemas/Severity", "#/components/schemas/CongestionState",
    "#/components/schemas/PublicSegmentState", "#/components/schemas/PublicAlert",
}


def charger(nom: str) -> dict:
    return yaml.safe_load((CONTRATS / nom).read_text(encoding="utf-8"))


def contrat_de(chemin: str) -> dict:
    return charger(f"{ROUTES[chemin][0]}.openapi.yaml")


def champs_de_l_adr() -> dict[str, set[str]]:
    """« **Champs publics, et seulement eux.** Congestion : `a`, `b`. Alerte : `c`, `d`. » (ADR-030, section 4.4)."""
    texte = ADR.read_text(encoding="utf-8")
    bloc = re.search(r"\*\*Champs publics, et seulement eux\.\*\*(.*?)Un test compare", texte, re.S).group(1)
    congestion = re.search(r"Congestion : (.*?)\. Alerte :", bloc, re.S).group(1)
    alerte = re.search(r"Alerte : (.*?)\.\s*$", bloc.strip(), re.S).group(1)
    return {"congestion": set(re.findall(r"`(\w+)`", congestion)), "alerte": set(re.findall(r"`(\w+)`", alerte))}


def references(noeud) -> set[str]:
    """Tous les `$ref` d'un morceau de contrat."""
    trouvees = set()
    if isinstance(noeud, dict):
        for cle, valeur in noeud.items():
            if cle == "$ref":
                trouvees.add(valeur)
            else:
                trouvees |= references(valeur)
    elif isinstance(noeud, list):
        for element in noeud:
            trouvees |= references(element)
    return trouvees


def noms(noeud) -> set[str]:
    """Tous les noms de propriétés déclarés dans un morceau de contrat."""
    trouves = set()
    if isinstance(noeud, dict):
        trouves |= set(noeud.get("properties", {}))
        for valeur in noeud.values():
            trouves |= noms(valeur)
    elif isinstance(noeud, list):
        for element in noeud:
            trouves |= noms(element)
    return trouves


def resoudre(contrat: dict, noeud):
    """Un schéma avec ses `$ref` locaux et communs remplacés (assez pour valider un exemple)."""
    if isinstance(noeud, dict):
        if "$ref" in noeud:
            fichier, _, chemin = noeud["$ref"].partition("#")
            doc = charger(fichier) if fichier else contrat
            cible = doc
            for morceau in chemin.strip("/").split("/"):
                cible = cible[morceau]
            return resoudre(doc, cible)
        return {cle: resoudre(contrat, valeur) for cle, valeur in noeud.items()}
    if isinstance(noeud, list):
        return [resoudre(contrat, element) for element in noeud]
    return noeud


class ContratPublic(unittest.TestCase):
    def test_les_deux_routes_publiques_existent_dans_le_contrat_du_service_qui_les_sert(self):
        for chemin, (service, operation, *_) in ROUTES.items():
            with self.subTest(chemin=chemin):
                item = contrat_de(chemin)["paths"][chemin]
                self.assertEqual(set(item) - {"parameters", "summary", "description"}, {"get"}, "lecture seule : GET et rien d'autre")
                self.assertEqual(item["get"]["operationId"], operation)

    def test_l_espace_public_ne_contient_que_ces_deux_routes(self):
        trouvees = set()
        for fichier in CONTRATS.glob("*.openapi.yaml"):
            trouvees |= {c for c in yaml.safe_load(fichier.read_text(encoding="utf-8"))["paths"] if c.startswith(ESPACE)}
        self.assertEqual(trouvees, set(ROUTES))

    def test_chaque_route_est_sans_jeton_sans_parametre_et_decrit_ses_reponses(self):
        for chemin in ROUTES:
            with self.subTest(chemin=chemin):
                operation = contrat_de(chemin)["paths"][chemin]["get"]
                self.assertEqual(operation["security"], [], "publique : security: []")
                self.assertNotIn("x-required-role", operation)
                self.assertNotIn("parameters", operation, "aucun paramètre en v1 : rien à injecter, rien à filtrer")
                self.assertEqual(set(operation["responses"]), {"200", "429", "5XX"}, "ni 401, ni 403 : il n'y a pas de jeton")
                self.assertEqual(operation["tags"], ["Public"])

    def test_la_reponse_dit_son_cache_et_les_erreurs_ont_le_format_commun(self):
        for chemin in ROUTES:
            with self.subTest(chemin=chemin):
                reponses = contrat_de(chemin)["paths"][chemin]["get"]["responses"]
                self.assertEqual(reponses["200"]["headers"]["Cache-Control"], {"$ref": "common.yaml#/components/headers/CacheControlPublic"})
                self.assertEqual(reponses["429"], {"$ref": "common.yaml#/components/responses/TooManyRequests"})
                self.assertEqual(reponses["5XX"], {"$ref": "common.yaml#/components/responses/ServerError"})
        self.assertIn("public, max-age=5", json.dumps(charger("common.yaml")["components"]["headers"]["CacheControlPublic"]))

    def test_les_champs_exposes_sont_exactement_la_liste_blanche_de_l_adr(self):
        adr = champs_de_l_adr()
        self.assertEqual(len(adr["congestion"]), 6)
        self.assertEqual(len(adr["alerte"]), 6)
        for chemin, (_, _, liste, element) in ROUTES.items():
            attendu = adr["congestion"] if "congestion" in chemin else adr["alerte"]
            schema = contrat_de(chemin)["components"]["schemas"][element]
            with self.subTest(route=chemin):
                self.assertEqual(set(schema["properties"]), attendu)
                self.assertEqual(set(schema["required"]), attendu, "chaque champ public est obligatoire : pas de champ qui apparaît parfois")

    def test_aucun_champ_n_est_admis_en_plus_et_les_listes_sont_bornees(self):
        for chemin, (_, _, liste, element) in ROUTES.items():
            schemas = contrat_de(chemin)["components"]["schemas"]
            with self.subTest(route=chemin):
                self.assertIs(schemas[element]["additionalProperties"], False)
                self.assertIs(schemas[liste]["additionalProperties"], False)
                self.assertEqual(set(schemas[liste]["properties"]), {"items"})
                self.assertGreater(schemas[liste]["properties"]["items"]["maxItems"], 0, "une liste publique est bornée")

    def test_aucun_champ_interne_n_apparait_dans_un_schema_public(self):
        for chemin, (_, _, liste, element) in ROUTES.items():
            schemas = contrat_de(chemin)["components"]["schemas"]
            for nom in (liste, element):
                with self.subTest(schema=nom):
                    self.assertEqual(noms(schemas[nom]) & set(INTERDITS), set(), "champ interdit par l'ADR-030, section 4.4")

    def test_les_schemas_publics_ne_referencent_aucun_schema_interne(self):
        for chemin, (_, _, liste, element) in ROUTES.items():
            schemas = contrat_de(chemin)["components"]["schemas"]
            with self.subTest(route=chemin):
                refs = references(schemas[liste]) | references(schemas[element])
                self.assertLessEqual(refs, REFERENCES_PERMISES, "un schéma public ne doit pas tirer Alert, Indicator, Provenance…")

    def test_les_descriptions_ne_laissent_pas_croire_que_le_modele_interne_sort(self):
        for chemin in ROUTES:
            description = contrat_de(chemin)["paths"][chemin]["get"]["description"]
            self.assertIn("ADR-030", description)
            self.assertIn("liste blanche", description)

    def test_les_exemples_respectent_leur_schema_et_pas_un_champ_de_plus(self):
        for chemin, (_, _, liste, _) in ROUTES.items():
            contrat = contrat_de(chemin)
            exemple = contrat["paths"][chemin]["get"]["responses"]["200"]["content"]["application/json"]["example"]
            schema = resoudre(contrat, contrat["components"]["schemas"][liste])
            with self.subTest(route=chemin):
                self.assertEqual(list(Draft202012Validator(schema).iter_errors(exemple)), [])
                avec_trop = json.loads(json.dumps(exemple))
                avec_trop["items"][0]["acknowledged_by"] = "operateur1"
                self.assertTrue(list(Draft202012Validator(schema).iter_errors(avec_trop)), "un champ de plus doit être refusé")

    def test_le_schema_refuse_un_champ_manquant_ou_un_type_faux(self):
        contrat = contrat_de("/api/v1/public/congestion")
        schema = resoudre(contrat, contrat["components"]["schemas"]["PublicCongestionList"])
        exemple = contrat["paths"]["/api/v1/public/congestion"]["get"]["responses"]["200"]["content"]["application/json"]["example"]
        valide = Draft202012Validator(schema)
        sans_champ = json.loads(json.dumps(exemple))
        del sans_champ["items"][0]["simulated"]
        mauvais_etat = json.loads(json.dumps(exemple))
        mauvais_etat["items"][0]["state"] = "JAMMED"
        mauvaise_date = json.loads(json.dumps(exemple))
        mauvaise_date["items"][0]["updated_at"] = "2026-11-20 08:20:00"
        for faux in (sans_champ, mauvais_etat, mauvaise_date):
            self.assertTrue(list(valide.iter_errors(faux)))

    def test_la_mention_donnees_simulees_est_un_champ_obligatoire(self):
        for chemin, (_, _, _, element) in ROUTES.items():
            self.assertIn("simulated", contrat_de(chemin)["components"]["schemas"][element]["required"])

    def test_les_valeurs_publiques_viennent_des_enumerations_internes(self):
        traitement, alerte = contrat_de("/api/v1/public/congestion")["components"]["schemas"], contrat_de("/api/v1/public/alerts")["components"]["schemas"]
        self.assertEqual(set(traitement["CongestionState"]["enum"]), {"UNKNOWN", "FREE_FLOW", "SLOW", "CONGESTED"})
        self.assertEqual(set(alerte["Severity"]["enum"]), {"INFO", "WARNING", "CRITICAL"})
        self.assertEqual(set(traitement["PublicSegmentState"]["properties"]["approach"]["enum"]), {"N", "E", "S", "W"})


if __name__ == "__main__":
    unittest.main()
