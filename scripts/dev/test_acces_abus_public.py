"""Essais d'abus de l'espace public (CIT-06) : le banc sait voir un abus qui aboutit.

Sans Docker : la passerelle est remplacée par un faux qui répond comme la vraie (CORS dédié, erreurs au format commun, journal sans
adresse, limite de débit), puis par des faux **défectueux**, un par défaut. Si un seul abus pouvait aboutir sans que le banc ne le voie,
un de ces tests échouerait. Lancement : python3 -m unittest discover -s scripts/dev -p "test_acces_abus_public.py".
"""

import json
import secrets
import tempfile
import unittest
from pathlib import Path

import acces as a

MATRICE = a.charger()
CITOYEN = "http://127.0.0.1:5174"
EQUIPE = "http://localhost:8080"
PROBLEME = {"type": "x", "title": "t", "status": 0, "code": "C", "detail": "d", "correlation_id": "c"}
SECURITE = {"cache-control": "no-store", "x-content-type-options": "nosniff", "server": "nginx"}


class FausseVraiePasserelle:
    """Se comporte comme la passerelle de CIT-06 ; chaque paramètre casse UNE protection."""

    passerelle = "http://passerelle"

    def __init__(self, **defauts):
        self.defauts = defauts
        self.env = {"CORS_PUBLIC_ORIGINS": CITOYEN, "CORS_ALLOWED_ORIGINS": EQUIPE}
        self.vus = {}
        self.journal = []

    def problem(self, statut, **plus):
        corps = {**PROBLEME, "status": statut, **plus}
        return statut, {**SECURITE, "content-type": "application/problem+json", **self.defauts.get("entetes_erreur", {})}, json.dumps(corps)

    def requete(self, methode, url, entetes=None, corps=None, delai=15):
        entetes = {k.lower(): v for k, v in (entetes or {}).items()}
        chemin = url.removeprefix(self.passerelle)
        origine, ip = entetes.get("origin"), entetes.get("x-forwarded-for")
        public = chemin.startswith("/api/v1/public/")
        if ip:
            self.journal.append(f"{ip if not public or self.defauts.get('journal_avec_adresse') else '-'} \"{methode} {chemin}\"")
        cors = {}
        autorisees = [CITOYEN] + ([EQUIPE] if self.defauts.get("equipe_lit_le_public") else []) + ([origine] if self.defauts.get("tout_ouvert") else [])
        if public and origine in autorisees or (not public and (origine == EQUIPE or (origine == CITOYEN and self.defauts.get("citoyen_lit_l_equipe")))):
            cors["access-control-allow-origin"] = origine
            if self.defauts.get("cookies"):
                cors["access-control-allow-credentials"] = "true"
        if methode == "OPTIONS":
            demande = entetes.get("access-control-request-method")
            jeton = "authorization" in entetes.get("access-control-request-headers", "")
            ouvert = self.defauts.get("preverif_ouverte") or (origine == CITOYEN and demande == "GET" and not jeton)
            return (204 if ouvert else 403), cors, ""
        if public and methode != "GET":
            return self.problem(405)
        if chemin.startswith("/api/v1/public/") and chemin not in MATRICE["api"]["publiques_lecture"]:
            statut = 400 if "//" in chemin or "%2e" in chemin else 404
            if self.defauts.get("fuite"):
                return statut, {**SECURITE, "server": "nginx/1.30.0"}, json.dumps({**PROBLEME, "status": statut, "detail": "upstream alerte injoignable"})
            if self.defauts.get("sans_entetes") and statut == 400:
                return statut, {"server": "nginx"}, json.dumps({**PROBLEME, "status": statut})
            return self.problem(statut)
        if not public:
            return 401, {**cors, **SECURITE}, json.dumps(PROBLEME)
        if not self.defauts.get("sans_limite"):
            self.vus[ip] = self.vus.get(ip, 0) + 1
            if self.vus[ip] > 12 and ip:
                statut, h, texte = self.problem(429)
                texte = json.dumps({**json.loads(texte), "code": "RATE_LIMITED"})
                h = {**h, "retry-after": "1"}
                if self.defauts.get("limite_sans_format"):
                    return 429, {}, "slow down"
                return 429, h, texte
        return 200, {**cors, "cache-control": "public, max-age=5"}, "{}"

    def journal_passerelle(self):
        return "\n".join(self.journal) if not self.defauts.get("journal_illisible") else ""


def jouer(**defauts):
    pile = FausseVraiePasserelle(**defauts)
    return a.essais_public_abus(pile, MATRICE, pause=lambda _: None)


def aboutis(essais):
    return [e for e in essais if not e.attendu and e.obtenu is True]


class PasserelleConforme(unittest.TestCase):
    def test_aucun_abus_n_aboutit_et_les_temoins_passent(self):
        essais = jouer()
        self.assertEqual(aboutis(essais), [])
        self.assertEqual([e for e in essais if not e.ok], [], [(e.operation, e.detail) for e in essais if not e.ok])
        self.assertEqual({e.famille for e in essais}, {a.FAMILLE_ABUS})

    def test_les_quatre_themes_sont_couverts(self):
        ressources = {e.ressource for e in jouer()}
        self.assertTrue({"CORS", "erreurs", "journal", "débit"} <= ressources, ressources)

    def test_il_y_a_des_temoins_pour_ne_pas_tout_fermer(self):
        temoins = [e for e in jouer() if e.attendu]
        self.assertEqual(len(temoins), 3)
        self.assertEqual({e.ressource for e in temoins}, {"CORS", "journal", "débit"})

    def test_les_adresses_du_banc_sont_inventees_et_hors_de_toute_vraie_adresse(self):
        for _ in range(50):
            self.assertRegex(a.adresse_jetable(), r"^10\.250\.\d{1,3}\.\d{1,3}$")


class LeBancVoitLesAbus(unittest.TestCase):
    def operations_aboutissant(self, **defauts):
        return {e.operation for e in aboutis(jouer(**defauts))}

    def test_une_origine_inconnue_qui_lit_est_vue(self):
        ops = self.operations_aboutissant(tout_ouvert=True)
        self.assertIn(f"origine inconnue lit {MATRICE['api']['publiques_lecture'][0]}", ops)

    def test_l_origine_de_l_equipe_qui_lit_le_public_est_vue(self):
        self.assertIn(f"origine du tableau de bord lit {MATRICE['api']['publiques_lecture'][0]}", self.operations_aboutissant(equipe_lit_le_public=True))

    def test_l_origine_citoyenne_qui_lit_l_api_d_equipe_est_vue(self):
        self.assertIn("origine citoyenne lit l'API d'équipe", self.operations_aboutissant(citoyen_lit_l_equipe=True))

    def test_les_cookies_entre_origines_sont_vus(self):
        self.assertIn("cookies autorisés entre origines (Allow-Credentials)", self.operations_aboutissant(cookies=True))

    def test_une_preverification_qui_accepte_l_ecriture_ou_le_jeton_est_vue(self):
        ops = self.operations_aboutissant(preverif_ouverte=True)
        self.assertIn("pré-vérification qui demande une écriture (POST)", ops)
        self.assertIn("pré-vérification qui demande le jeton d'équipe (Authorization)", ops)

    def test_une_erreur_qui_laisse_voir_l_interieur_est_vue(self):
        ops = self.operations_aboutissant(fuite=True)
        self.assertTrue(any("détail interne ou version lisible" in o for o in ops), ops)

    def test_une_erreur_sans_en_tetes_de_securite_est_vue(self):
        ops = self.operations_aboutissant(sans_entetes=True)
        self.assertTrue(any("format, cache ou en-têtes de sécurité manquants" in o and "chemin refusé" in o for o in ops), ops)

    def test_l_adresse_d_un_citoyen_dans_le_journal_est_vue(self):
        self.assertIn("adresse d'un citoyen dans le journal de la passerelle", self.operations_aboutissant(journal_avec_adresse=True))

    def test_l_absence_de_limite_de_debit_est_vue(self):
        ops = self.operations_aboutissant(sans_limite=True)
        self.assertTrue(any("lectures publiques d'affilée sans être limité" in o for o in ops), ops)

    def test_un_refus_de_debit_sans_le_format_commun_est_vu(self):
        ops = self.operations_aboutissant(limite_sans_format=True)
        self.assertTrue(any("refus de débit sans le format commun" in o for o in ops), ops)

    def test_un_journal_illisible_n_est_pas_un_succes(self):
        essais = jouer(journal_illisible=True)
        journal = [e for e in essais if e.ressource == "journal"]
        self.assertEqual([e.obtenu for e in journal], [None])
        self.assertFalse(journal[0].ok)

    def test_un_reseau_en_panne_n_est_jamais_un_succes(self):
        class Muette(FausseVraiePasserelle):
            def requete(self, *args, **kwargs):
                return 0, {}, ""

            def journal_passerelle(self):
                return ""

        essais = a.essais_public_abus(Muette(), MATRICE, pause=lambda _: None)
        self.assertTrue(all(not e.ok for e in essais), "rien ne réussit quand le réseau ne répond pas")
        self.assertEqual([e for e in essais if not e.attendu and e.obtenu is False], [], "aucun refus ne doit être déduit d'un réseau muet")


class SecretsDuFront(unittest.TestCase):
    # Les valeurs sont tirées à chaque exécution : le dépôt est public et ne contient aucune valeur ressemblant à un secret, même inventée.
    ENV = {"JWT_SECRET": secrets.token_urlsafe(24), "PG_PASSWORD_APP": secrets.token_urlsafe(24), "PORT": "8000",
           "COURT_SECRET": "abc", "JWT_PLACEHOLDER_KEY": "change-me-local"}

    def front(self, contenu_src="export const x = 1;", contenu_dist="var a=1;"):
        dossier = Path(tempfile.mkdtemp())
        (dossier / "citizen" / "src").mkdir(parents=True)
        (dossier / "citizen" / "dist").mkdir()
        (dossier / "citizen" / "src" / "api.ts").write_text(contenu_src, encoding="utf-8")
        (dossier / "citizen" / "dist" / "app.js").write_text(contenu_dist, encoding="utf-8")
        (dossier / "citizen" / "index.html").write_text("<html></html>", encoding="utf-8")
        return dossier

    def test_un_front_propre_donne_un_essai_sans_abus(self):
        essais = a.essais_front(self.ENV, self.front())
        self.assertEqual([e.obtenu for e in essais], [False])
        self.assertTrue(essais[0].ok)

    def test_une_valeur_secrete_dans_les_sources_ou_la_version_construite_est_vue_sans_etre_recopiee(self):
        for sources, construit in ((self.ENV["JWT_SECRET"], ""), ("", self.ENV["PG_PASSWORD_APP"])):
            essais = a.essais_front(self.ENV, self.front(f"const k = '{sources}';", f"var k='{construit}';"))
            self.assertIs(essais[0].obtenu, True)
            self.assertNotIn(self.ENV["JWT_SECRET"], essais[0].detail, "la valeur n'est jamais recopiée")
            self.assertNotIn(self.ENV["PG_PASSWORD_APP"], essais[0].detail)
            self.assertRegex(essais[0].detail, r"JWT_SECRET|PG_PASSWORD_APP")

    def test_les_valeurs_trop_courtes_ou_d_exemple_et_les_variables_sans_secret_sont_ignorees(self):
        essais = a.essais_front(self.ENV, self.front("const a = 'abc'; const p = 'change-me-local'; const port = '8000';"))
        self.assertEqual([e.obtenu for e in essais], [False])

    def test_sans_version_construite_le_banc_le_dit(self):
        dossier = self.front()
        import shutil
        shutil.rmtree(dossier / "citizen" / "dist")
        self.assertIn("dist/ absent", a.essais_front(self.ENV, dossier)[0].detail)

    def test_le_vrai_front_du_depot_ne_contient_aucune_valeur_du_fichier_env_d_exemple(self):
        exemple = {}
        for ligne in (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8").splitlines():
            if "=" in ligne and not ligne.startswith("#"):
                cle, _, valeur = ligne.partition("=")
                exemple[cle.strip()] = valeur.strip()
        essais = a.essais_front(exemple)
        self.assertEqual([e.obtenu for e in essais], [False], essais[0].detail)


if __name__ == "__main__":
    unittest.main()
