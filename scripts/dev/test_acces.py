"""La matrice d'accès et ses essais (CLD-18) : lecture de la matrice, calcul de l'accès attendu, comparaison aux catalogues, détection.

Sans Docker : la pile est remplacée par un faux qui répond comme une passerelle (ou comme une passerelle trop permissive). Le test
le plus important est le dernier groupe : **le banc sait voir un accès interdit accordé**. Lancement :
python3 -m unittest discover -s scripts/dev -p "test_acces.py"  (Windows : py -3 ...).
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

import acces as a

RACINE = Path(__file__).resolve().parents[2]
MATRICE = a.charger()
ROUTES = [
    {"method": "GET", "pattern": "^/api/v1/indicators$", "role": "viewer"},
    {"method": "POST", "pattern": "^/api/v1/alerts/[^/]+/resolve$", "role": "operator"},
    {"method": "GET", "pattern": "^/api/v1/users$", "role": "admin"},
    {"method": "POST", "pattern": "^/api/v1/auth/login$", "role": None},
]


class LectureDeLaMatrice(unittest.TestCase):
    def test_le_fichier_du_depot_est_valide(self):
        self.assertEqual(MATRICE["api"]["roles"], ["viewer", "operator", "admin"])
        self.assertEqual(set(MATRICE["postgres"]["comptes"]), {"svc_app", "svc_traitement", "svc_alerte", "svc_lecture"})
        self.assertEqual(set(MATRICE["mongo"]["utilisateurs"]), {"svc_collecte", "svc_traitement", "svc_reponse", "svc_backend", "svc_ml"})
        self.assertIs(MATRICE["kafka"]["appliqué"], False)

    def charger_modifiee(self, modifier):
        document = json.loads(json.dumps(MATRICE))
        modifier(document)
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "m.json"
            chemin.write_text(json.dumps(document), encoding="utf-8")
            return a.charger(chemin)

    def test_un_role_inconnu_un_privilege_inconnu_une_collection_inconnue_sont_refuses(self):
        with self.assertRaises(a.Erreur):
            self.charger_modifiee(lambda d: d["api"]["ressources"][0].update(lecture="superadmin"))
        with self.assertRaises(a.Erreur):
            self.charger_modifiee(lambda d: d["postgres"]["schemas"]["dwh"].update(svc_lecture=["TRUNCATE"]))
        with self.assertRaises(a.Erreur):
            self.charger_modifiee(lambda d: d["mongo"]["utilisateurs"]["svc_ml"]["droits"].update(fantome=["find"]))

    def test_chaque_utilisateur_et_chaque_compte_a_un_essai_autorise_et_un_essai_refuse(self):
        for compte in MATRICE["postgres"]["comptes"]:
            self.assertEqual(set(MATRICE["postgres"]["essais"][compte]), {"autorise", "refuse"})
        for utilisateur in MATRICE["mongo"]["utilisateurs"]:
            self.assertEqual(set(MATRICE["mongo"]["essais"][utilisateur]), {"autorise", "refuse"})

    def test_la_matrice_postgres_suit_le_principe_un_service_ecrit_dans_ses_schemas(self):
        schemas = MATRICE["postgres"]["schemas"]
        ecrivains = {schema: [c for c, p in droits.items() if set(p) & {"INSERT", "UPDATE", "DELETE"}] for schema, droits in schemas.items()}
        self.assertEqual(ecrivains, {"app": ["svc_app"], "dwh": ["svc_traitement"], "alertes": ["svc_alerte"], "ops": []})
        self.assertNotIn("svc_lecture", [c for liste in ecrivains.values() for c in liste])

    def test_aucun_service_mongo_ne_peut_supprimer(self):
        for utilisateur, definition in MATRICE["mongo"]["utilisateurs"].items():
            for collection, actions in definition["droits"].items():
                self.assertNotIn("remove", actions, f"{utilisateur} sur {collection}")


class AccesAttendu(unittest.TestCase):
    def attendu(self, sujet, methode, chemin):
        return a.acces_attendu(MATRICE, sujet, methode, chemin)[0]

    def test_les_roles_sont_ordonnes(self):
        self.assertEqual([a.rang(r, ["viewer", "operator", "admin"]) for r in ("anonyme", "viewer", "operator", "admin")], [-1, 0, 1, 2])

    def test_lecture_et_action_n_ont_pas_le_meme_role_exige(self):
        self.assertEqual([self.attendu(s, "GET", "/api/v1/alerts") for s in a.SUJETS_API], [False, True, True, True])
        self.assertEqual([self.attendu(s, "POST", "/api/v1/alerts") for s in a.SUJETS_API], [False, False, True, True])
        self.assertEqual([self.attendu(s, "PATCH", "/api/v1/alert-rules") for s in a.SUJETS_API], [False, False, False, True])

    def test_les_comptes_sont_reserves_a_l_administrateur_meme_en_lecture(self):
        self.assertEqual([self.attendu(s, "GET", "/api/v1/users") for s in a.SUJETS_API], [False, False, False, True])

    def test_les_routes_publiques_sont_ouvertes_a_l_anonyme(self):
        self.assertTrue(self.attendu("anonyme", "POST", "/api/v1/auth/login"))
        self.assertTrue(self.attendu("anonyme", "GET", "/api/v1/health"))

    def test_une_route_absente_de_la_matrice_est_une_erreur_pas_un_acces_par_defaut(self):
        with self.assertRaises(a.Erreur):
            a.acces_attendu(MATRICE, "admin", "GET", "/api/v1/secrets")

    def test_alert_rules_n_est_pas_confondu_avec_alerts(self):
        self.assertEqual(a.acces_attendu(MATRICE, "admin", "GET", "/api/v1/alert-rules")[2], "regles-alerte")
        self.assertEqual(a.acces_attendu(MATRICE, "admin", "GET", "/api/v1/alerts")[2], "alertes")

    def test_les_chemins_de_test_visent_des_identifiants_inexistants(self):
        self.assertEqual(a.chemin_concret(r"^/api/v1/alerts/[^/]+/resolve$"), "/api/v1/alerts/essai-inconnu/resolve")
        self.assertEqual(a.chemin_concret(r"^/api/v1/alert\-rules$"), "/api/v1/alert-rules")
        self.assertEqual(a.chemin_declare(r"^/api/v1/alerts/[^/]+/resolve$"), "/api/v1/alerts")

    def test_la_matrice_declaree_est_celle_des_contrats_openapi(self):
        self.assertEqual(a.verifier_la_matrice_contre_les_contrats(MATRICE, a.routes_du_contrat()), [])

    def test_un_contrat_plus_permissif_que_la_matrice_est_signale(self):
        routes = a.routes_du_contrat()
        routes[next(i for i, r in enumerate(routes) if r["pattern"] == "^/api/v1/users$" and r["method"] == "GET")]["role"] = "viewer"
        ecarts = a.verifier_la_matrice_contre_les_contrats(MATRICE, routes)
        self.assertEqual(ecarts, ["GET /api/v1/users : matrice admin, contrats viewer"])

    def test_toutes_les_routes_du_contrat_sont_dans_la_matrice(self):
        for route in a.routes_du_contrat():
            a.acces_attendu(MATRICE, "admin", route["method"], a.chemin_declare(route["pattern"]))


class Classement(unittest.TestCase):
    def test_http(self):
        self.assertIs(a.classer_http(401), False)
        self.assertIs(a.classer_http(403), False)
        self.assertIs(a.classer_http(200), True)
        self.assertIs(a.classer_http(422), True, "le corps invalide prouve que l'autorisation est passée")
        self.assertIs(a.classer_http(404), True, "identifiant inconnu : le service a été atteint")
        self.assertIsNone(a.classer_http(429))
        self.assertIsNone(a.classer_http(503), "une panne de service n'est ni un accès ni un refus")
        self.assertIsNone(a.classer_http(0))
        self.assertIs(a.classer_http(404, hors_passerelle=True), False)

    def test_un_essai_n_est_conforme_que_si_il_a_ete_joue_et_conforme(self):
        base = dict(famille="f", sujet="s", ressource="r", operation="o", detail="d")
        self.assertTrue(a.Essai(attendu=True, obtenu=True, **base).ok)
        self.assertTrue(a.Essai(attendu=False, obtenu=False, **base).ok)
        self.assertFalse(a.Essai(attendu=False, obtenu=True, **base).ok)
        self.assertFalse(a.Essai(attendu=True, obtenu=None, **base).ok, "un essai raté n'est pas un succès")


CATALOGUE_PG = ("P|svc_lecture|dwh|SELECT|10|10\nP|svc_lecture|dwh|INSERT|0|10\nP|svc_traitement|dwh|INSERT|10|10\nP|svc_lecture|alertes|SELECT|4|4\n"
                "A|svc_lecture|f|f|f|f|t\nC|svc_lecture|dwh|f\nC|svc_app|app|t\n")


class CataloguePostgres(unittest.TestCase):
    def test_lecture_du_catalogue(self):
        catalogue = a.lire_catalogue_pg(CATALOGUE_PG)
        self.assertEqual(catalogue["privileges"][("svc_lecture", "dwh", "SELECT")], (10, 10))
        self.assertEqual(catalogue["administration"]["svc_lecture"], [False, False, False, False, True])
        self.assertTrue(catalogue["creation"][("svc_app", "app")])

    def cellule(self, essais, compte, schema, privilege):
        return next(e for e in essais if e.sujet == compte and e.ressource == f"{schema}.*" and e.operation == privilege)

    def test_un_droit_partiel_n_est_ni_un_acces_ni_un_refus(self):
        catalogue = a.lire_catalogue_pg("P|svc_lecture|dwh|SELECT|7|10\n")
        essai = self.cellule(a.comparer_catalogue_pg(MATRICE, catalogue), "svc_lecture", "dwh", "SELECT")
        self.assertIsNone(essai.obtenu)
        self.assertFalse(essai.ok)
        self.assertIn("droit partiel", essai.detail)

    def test_un_privilege_en_trop_est_un_acces_interdit_accorde(self):
        catalogue = a.lire_catalogue_pg("P|svc_lecture|dwh|INSERT|10|10\n")
        essais = a.comparer_catalogue_pg(MATRICE, catalogue)
        self.assertEqual([(e.sujet, e.ressource, e.operation) for e in a.accord_interdit(essais)], [("svc_lecture", "dwh.*", "INSERT")])

    def test_un_privilege_manquant_est_un_refus_inattendu_pas_un_acces_interdit(self):
        catalogue = a.lire_catalogue_pg("P|svc_lecture|dwh|SELECT|0|10\n")
        essais = a.comparer_catalogue_pg(MATRICE, catalogue)
        self.assertEqual([e.operation for e in a.refus_inattendu(essais) if e.sujet == "svc_lecture" and e.ressource == "dwh.*"], ["SELECT"])
        self.assertEqual(a.accord_interdit(essais), [])

    def test_un_compte_de_service_administrateur_est_un_acces_interdit_accorde(self):
        essais = a.comparer_catalogue_pg(MATRICE, a.lire_catalogue_pg("A|svc_traitement|t|f|f|f|t\n"))
        self.assertIn("svc_traitement", [e.sujet for e in a.accord_interdit(essais) if e.ressource == "administration"])

    def test_creer_dans_un_schema_n_est_permis_qu_a_svc_app_sur_app(self):
        essais = a.comparer_catalogue_pg(MATRICE, a.lire_catalogue_pg("C|svc_alerte|dwh|t\nC|svc_app|app|t\n"))
        self.assertEqual([(e.sujet, e.ressource) for e in a.accord_interdit(essais)], [("svc_alerte", "dwh")])


class CatalogueMongo(unittest.TestCase):
    def reel(self):
        return {"collections": list(MATRICE["mongo"]["collections"]),
                "utilisateurs": {u: {c: sorted(actions) for c, actions in d["droits"].items()} for u, d in MATRICE["mongo"]["utilisateurs"].items()}}

    def test_une_pile_conforme_n_a_aucun_ecart(self):
        essais = a.comparer_catalogue_mongo(MATRICE, self.reel())
        self.assertTrue(all(e.ok for e in essais))
        self.assertEqual(len(essais), 5 * 7 * 4)

    def test_un_droit_de_suppression_en_trop_est_detecte(self):
        reel = self.reel()
        reel["utilisateurs"]["svc_collecte"]["raw_events"].append("remove")
        self.assertEqual([(e.sujet, e.ressource, e.operation) for e in a.accord_interdit(a.comparer_catalogue_mongo(MATRICE, reel))],
                         [("svc_collecte", "raw_events", "remove")])

    def test_une_collection_absente_de_la_matrice_est_signalee(self):
        reel = self.reel()
        reel["collections"].append("secrets")
        essais = a.comparer_catalogue_mongo(MATRICE, reel)
        self.assertTrue(any(e.ressource == "secrets" and not e.ok for e in essais))

    def test_les_droits_herites_d_une_collection_manquante_sont_un_refus_inattendu(self):
        reel = self.reel()
        reel["utilisateurs"]["svc_traitement"].pop("ingestion_runs")
        manquants = a.refus_inattendu(a.comparer_catalogue_mongo(MATRICE, reel))
        self.assertEqual(sorted(e.operation for e in manquants), ["find", "insert", "update"])


class PasserelleFausse:
    """Une passerelle fabriquée à la main : `permissive` laisse passer un rôle trop faible sur les routes d'administration."""

    EXIGE = {"/api/v1/indicators": "viewer", "/api/v1/alerts/essai-inconnu/resolve": "operator", "/api/v1/users": "admin"}
    RANG = {None: -1, "viewer": 0, "operator": 1, "admin": 2}

    def __init__(self, permissive: bool = False):
        self.passerelle, self.permissive, self.appels = "http://passerelle", permissive, []

    def appel_conclusif(self, methode, url, jeton=None, corps=None, delai=15, hors_passerelle=False):
        chemin = url.removeprefix(self.passerelle)
        self.appels.append((methode, chemin, jeton))
        if chemin == "/api/v1/measurements":
            return 404
        if chemin == "/api/v1/auth/login":
            return 422
        exige = self.EXIGE[chemin]
        if jeton is None:
            return 401
        if self.permissive and exige == "admin" and jeton == "operator":
            return 200
        return 403 if self.RANG[jeton] < self.RANG[exige] else 200


class BancEnFace(unittest.TestCase):
    JETONS = {"viewer": "viewer", "operator": "operator", "admin": "admin"}

    def test_une_passerelle_conforme_donne_zero_ecart(self):
        essais = a.essais_api(PasserelleFausse(), MATRICE, self.JETONS, ROUTES, pause=lambda _: None)
        self.assertEqual(len(essais), 4 * 4 + 4)
        self.assertEqual([e for e in essais if not e.ok], [])
        self.assertEqual(a.accord_interdit(essais), [])

    def test_le_banc_voit_un_role_trop_faible_qui_passe(self):
        essais = a.essais_api(PasserelleFausse(permissive=True), MATRICE, self.JETONS, ROUTES, pause=lambda _: None)
        interdits = a.accord_interdit(essais)
        self.assertEqual([(e.sujet, e.operation) for e in interdits], [("operator", "GET /api/v1/users")])

    def test_chaque_route_est_essayee_avec_les_quatre_sujets_dont_l_anonyme_sans_jeton(self):
        pile = PasserelleFausse()
        a.essais_api(pile, MATRICE, self.JETONS, ROUTES, pause=lambda _: None)
        pour_users = [jeton for _, chemin, jeton in pile.appels if chemin == "/api/v1/users"]
        self.assertEqual(pour_users, [None, "viewer", "operator", "admin"])

    def test_les_essais_ne_modifient_rien_les_corps_sont_vides_et_les_identifiants_inconnus(self):
        pile = PasserelleFausse()
        a.essais_api(pile, MATRICE, self.JETONS, ROUTES, pause=lambda _: None)
        for _, chemin, _ in pile.appels:
            self.assertNotRegex(chemin, r"/[0-9a-f]{8}-[0-9a-f]{4}-", "aucun vrai identifiant")

    def test_la_mesure_deposee_est_refusee_par_la_passerelle_pour_tous_les_sujets(self):
        essais = [e for e in a.essais_api(PasserelleFausse(), MATRICE, self.JETONS, [], pause=lambda _: None)]
        self.assertEqual([(e.sujet, e.attendu, e.obtenu) for e in essais], [(s, False, False) for s in a.SUJETS_API])

    def test_un_exemple_autorise_et_un_refuse_par_sujet(self):
        essais = a.essais_api(PasserelleFausse(), MATRICE, self.JETONS, ROUTES, pause=lambda _: None)
        exemples = a.exemples_par_sujet(essais, ("api",))
        self.assertEqual(set(exemples), set(a.SUJETS_API))
        for sujet, (autorise, refuse) in exemples.items():
            self.assertTrue(autorise.attendu and refuse is not None and not refuse.attendu, sujet)

    def test_les_exemples_nommes_par_la_matrice_existent_et_sont_conformes_au_contrat(self):
        for sujet, paire in MATRICE["api"]["exemples"].items():
            self.assertEqual(set(paire), {"autorise", "refuse"}, sujet)
            for cle, operation in paire.items():
                methode, _, chemin = operation.partition(" ")
                chemin = chemin.replace("/…", "")
                attendu = a.acces_attendu(MATRICE, sujet, methode, chemin)[0] if chemin != "/api/v1/measurements" else False
                self.assertEqual(attendu, cle == "autorise", f"{sujet} : {operation}")

    def test_le_resume_compte_les_acces_et_les_refus_separement(self):
        essais = a.essais_api(PasserelleFausse(), MATRICE, self.JETONS, ROUTES, pause=lambda _: None)
        (famille, accordes, attendus_accordes, refuses, attendus_refuses), = a.resume_par_famille(essais)
        self.assertEqual((famille, accordes, attendus_accordes), ("api", attendus_accordes, attendus_accordes))
        self.assertEqual((refuses, attendus_refuses), (attendus_refuses, attendus_refuses))
        self.assertGreater(attendus_refuses, 0)


class PasserelleCitoyenne:
    """La passerelle devant les routes publiques (CIT-02). Réglages de panne : une écriture qui passe, un chemin inconnu qui répond,
    une lecture qui exige un jeton."""

    PUBLIQUES = ("/api/v1/public/congestion", "/api/v1/public/alerts")

    def __init__(self, ecriture_ouverte=False, espace_ouvert=False, lecture_protegee=False):
        self.passerelle, self.appels = "http://passerelle", []
        self.ecriture_ouverte, self.espace_ouvert, self.lecture_protegee = ecriture_ouverte, espace_ouvert, lecture_protegee

    def appel_conclusif(self, methode, url, jeton=None, corps=None, delai=15, hors_passerelle=False):
        chemin = url.removeprefix(self.passerelle)
        self.appels.append((methode, chemin, jeton))
        if chemin in self.PUBLIQUES:
            if methode == "GET":
                return 401 if self.lecture_protegee and jeton is None else 200
            return 200 if self.ecriture_ouverte and jeton == "operator" else 405
        return 200 if self.espace_ouvert and jeton == "viewer" else 404


class EspacePublic(unittest.TestCase):
    """L'application citoyenne (ADR-030) : lecture ouverte à tous, écritures refusées à tous, espace fermé hors liste."""

    JETONS = {"viewer": "viewer", "operator": "operator", "admin": "admin"}

    def essais(self, pile):
        return a.essais_public(pile, MATRICE, self.JETONS, pause=lambda _: None)

    def test_la_matrice_declare_les_routes_publiques_en_lecture_seule(self):
        api = MATRICE["api"]
        self.assertEqual(api["publiques_lecture"], ["/api/v1/public/congestion", "/api/v1/public/alerts"])
        self.assertTrue(set(api["publiques_lecture"]).isdisjoint(api["publiques"]), "ni la sonde ni la connexion")
        for chemin in api["espace_public_interdit"]:
            self.assertTrue(chemin.startswith(a.ESPACE_PUBLIC))
            self.assertNotIn(chemin, api["publiques_lecture"])

    def test_la_lecture_est_ouverte_a_tous_et_toute_ecriture_est_refusee_a_tous(self):
        for sujet in a.SUJETS_API:
            for chemin in MATRICE["api"]["publiques_lecture"]:
                self.assertTrue(a.acces_attendu(MATRICE, sujet, "GET", chemin)[0], (sujet, chemin))
                for methode in a.METHODES_D_ECRITURE:
                    self.assertFalse(a.acces_attendu(MATRICE, sujet, methode, chemin)[0], (sujet, methode, chemin))

    def test_une_passerelle_conforme_donne_zero_ecart(self):
        essais = self.essais(PasserelleCitoyenne())
        self.assertEqual([e for e in essais if not e.ok], [])
        self.assertEqual(a.accord_interdit(essais), [])
        self.assertEqual(len(essais), 4 * 2 * (1 + 4) + 4 * len(MATRICE["api"]["espace_public_interdit"]))
        self.assertEqual({e.famille for e in essais}, {"api public"})

    def test_chaque_methode_d_ecriture_est_essayee_avec_les_quatre_sujets_y_compris_l_administrateur(self):
        pile = PasserelleCitoyenne()
        self.essais(pile)
        ecritures = {(m, j) for m, c, j in pile.appels if c == "/api/v1/public/alerts" and m != "GET"}
        self.assertEqual(ecritures, {(m, j) for m in a.METHODES_D_ECRITURE for j in (None, "viewer", "operator", "admin")})

    def test_une_ecriture_qui_passe_est_un_acces_interdit_accorde(self):
        interdits = a.accord_interdit(self.essais(PasserelleCitoyenne(ecriture_ouverte=True)))
        self.assertEqual({(e.sujet, e.operation.split()[0]) for e in interdits}, {("operator", m) for m in a.METHODES_D_ECRITURE})

    def test_un_chemin_de_l_espace_public_qui_repond_est_un_acces_interdit_accorde(self):
        interdits = a.accord_interdit(self.essais(PasserelleCitoyenne(espace_ouvert=True)))
        self.assertEqual({e.sujet for e in interdits}, {"viewer"})
        self.assertEqual({e.operation for e in interdits}, {f"GET {c}" for c in MATRICE["api"]["espace_public_interdit"]})

    def test_une_lecture_publique_qui_exige_un_jeton_est_un_refus_inattendu(self):
        inattendus = a.refus_inattendu(self.essais(PasserelleCitoyenne(lecture_protegee=True)))
        self.assertEqual({(e.sujet, e.operation) for e in inattendus}, {("anonyme", f"GET {c}") for c in MATRICE["api"]["publiques_lecture"]})

    def test_une_ecriture_non_concluante_n_est_pas_un_refus(self):
        class Limitee(PasserelleCitoyenne):
            def appel_conclusif(self, methode, url, jeton=None, corps=None, delai=15, hors_passerelle=False):
                return 429

        essais = self.essais(Limitee())
        self.assertTrue(all(e.obtenu is None for e in essais))
        self.assertFalse(any(e.ok for e in essais))

    def test_405_n_est_un_refus_que_depuis_la_passerelle(self):
        self.assertIs(a.classer_http(405, hors_passerelle=True), False)
        self.assertIs(a.classer_http(405), True, "d'un service direct, 405 prouve seulement que la route est atteinte")

    def test_les_routes_de_l_espace_public_ne_sont_pas_rejouees_par_les_essais_de_l_api(self):
        routes = a.routes_du_contrat()
        pile = PasserelleFausse()
        public = [r for r in routes if r["pattern"].startswith("^/api/v1/public/")]
        self.assertEqual(len(public), 2)
        essais = a.essais_api(pile, MATRICE, self.JETONS, [r for r in ROUTES] + public, pause=lambda _: None)
        self.assertFalse([c for _, c, _ in pile.appels if c.startswith("/api/v1/public/")])
        self.assertEqual(len(essais), 4 * 4 + 4)

    def test_une_route_publique_de_la_matrice_absente_des_contrats_est_signalee(self):
        routes = [r for r in a.routes_du_contrat() if r["pattern"] != "^/api/v1/public/alerts$"]
        ecarts = a.verifier_la_matrice_contre_les_contrats(MATRICE, routes)
        self.assertEqual(ecarts, ["GET /api/v1/public/alerts : publique dans la matrice, absente ou protégée dans les contrats"])

    def test_une_route_de_l_espace_public_absente_de_la_matrice_est_signalee(self):
        matrice = json.loads(json.dumps(MATRICE))
        matrice["api"]["publiques_lecture"].remove("/api/v1/public/alerts")
        ecarts = a.verifier_la_matrice_contre_les_contrats(matrice, a.routes_du_contrat())
        self.assertTrue(any("dans l'espace public des contrats, absente de la matrice" in e for e in ecarts), ecarts)

    def test_une_route_publique_devenue_protegee_dans_les_contrats_est_signalee(self):
        routes = a.routes_du_contrat()
        for route in routes:
            if route["pattern"] == "^/api/v1/public/alerts$":
                route["role"] = "viewer"
        ecarts = a.verifier_la_matrice_contre_les_contrats(MATRICE, routes)
        self.assertTrue(any("publique dans la matrice, absente ou protégée" in e for e in ecarts), ecarts)


class CompteJetable(unittest.TestCase):
    def test_les_comptes_d_essai_sont_supprimes_meme_si_un_essai_echoue(self):
        class Pile:
            passerelle = "http://passerelle"
            ports = {}

            def __init__(self):
                self.crees, self.supprimes = [], []

            def creer_compte(self, nom, role, mot_de_passe):
                self.crees.append(nom)

            def jeton(self, nom, mot_de_passe):
                return "jeton"

            def appel_conclusif(self, *args, **kwargs):
                raise RuntimeError("panne pendant les essais")

            def supprimer_compte(self, nom):
                self.supprimes.append(nom)

        pile = Pile()
        with self.assertRaises(RuntimeError):
            a.executer(pile, MATRICE, ROUTES, afficher=lambda _: None, pause=lambda _: None)
        self.assertEqual(len(pile.crees), 3)
        self.assertEqual(sorted(pile.supprimes), sorted(pile.crees))
        for nom in pile.crees:
            self.assertRegex(nom, r"^acces-(viewer|operator|admin)-[0-9a-f]{6}$")


class Documentation(unittest.TestCase):
    def test_les_commandes_existent_dans_dev_py(self):
        import dev

        dev.build_parser().parse_args(["acces"])

    def test_les_sujets_kafka_declares_existent(self):
        sujets = json.loads((RACINE / "contracts" / "topics.json").read_text(encoding="utf-8"))["topics"]
        self.assertGreaterEqual(len(sujets), 6)
        for definition in sujets.values():
            self.assertTrue(definition["producers"], "chaque sujet a un producteur déclaré")

    def test_le_document_de_preuve_cite_chaque_ressource_compte_et_utilisateur_de_la_matrice(self):
        document = (RACINE / "docs" / "05-cloud-aws" / "matrice-acces.md").read_text(encoding="utf-8")
        for ressource in MATRICE["api"]["ressources"]:
            for chemin in ressource["chemins"]:
                self.assertIn(chemin.removeprefix("/api/v1"), document, chemin)
        for nom in (*MATRICE["postgres"]["comptes"], *MATRICE["mongo"]["utilisateurs"], *MATRICE["mongo"]["collections"]):
            self.assertIn(f"`{nom}`", document, nom)
        for sujet in json.loads((RACINE / "contracts" / "topics.json").read_text(encoding="utf-8"))["topics"]:
            self.assertIn(f"`{sujet}`", document, sujet)

    def test_les_commandes_de_la_matrice_ne_contiennent_aucun_secret(self):
        texte = (RACINE / "ops" / "matrice-acces.json").read_text(encoding="utf-8")
        self.assertNotRegex(texte, r"(?i)(password|passwd|secret|token)\s*[:=]\s*['\"][^'\"$]{4,}")
        self.assertEqual(sorted(set(re.findall(r"MONGO_PASSWORD_[A-Z]+", texte))), ["MONGO_PASSWORD_BACKEND", "MONGO_PASSWORD_COLLECTE", "MONGO_PASSWORD_ML", "MONGO_PASSWORD_REPONSE", "MONGO_PASSWORD_TRAITEMENT"])


if __name__ == "__main__":
    unittest.main()
