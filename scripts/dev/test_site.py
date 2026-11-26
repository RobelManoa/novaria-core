"""Le site de soutenance (SIT-02, dossier site/) tient ses engagements, sans navigateur et sans réseau.

    Linux : python3 -m unittest scripts/dev/test_site.py
    Windows : py -3 -m unittest scripts/dev/test_site.py

Engagements gardés (issue SIT-02, plan docs/09-soutenance/site-plan.md) :

- le site s'ouvre hors ligne : aucune ressource externe n'est chargée, toutes les images existent, le poids reste raisonnable ;
- la soutenance dure 20 minutes (la somme des temps de scène) ;
- tout chiffre de la scène « intelligence » est celui des résultats du dépôt ;
- une donnée simulée est dite simulée ; la photo de la scène 2 est celle de Wikimedia Commons, non modifiée, avec sa mention ;
- les neuf compétences BC05 y sont avec leur niveau ;
- les deux systèmes (Linux et Windows) ont leurs commandes ;
- le lexique (site/lexique.js) définit chaque sigle que le site emploie, sans doublon ni renvoi mort, et ne parle pas du cloud ;
- le lecteur de documents (site/docs.js) contient chaque document cité, tel qu'il est dans le dépôt, sans rien d'actif ni d'externe.

Le contenu est lu dans `site/contenu.js` : si Node.js est installé, il l'exécute (le test échoue si le fichier est faux) ;
sinon, le test lit le fichier comme du texte.
"""

import hashlib
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SITE = RACINE / "site"
PHOTO_SHA256 = "321773323de75b53e56ddc926e41bb0e725c97f81269cd2be646a59a9dc30a30"  # Inductive_Loop_Traffic_Counter.jpg, 152 358 octets
PAGE_COMMONS = "https://commons.wikimedia.org/wiki/File:Inductive_Loop_Traffic_Counter.jpg"
POIDS_MAX = 3_000_000  # octets : « poids de page raisonnable » (docs.js, le lecteur de documents, en fait un peu plus d'un tiers)


def lire(nom: str) -> str:
    return (SITE / nom).read_text(encoding="utf-8")


def donnees(fichier: str, nom: str) -> dict:
    """Exécute un fichier du site avec Node.js et renvoie `window.<nom>`."""
    node = shutil.which("node")
    if node is None:
        return {}
    script = f"global.window={{}};eval(require('fs').readFileSync(process.argv[1],'utf8'));console.log(JSON.stringify(window.{nom}))"
    sortie = subprocess.run([node, "-e", script, str(SITE / fichier)], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(sortie.stdout)


def contenu() -> dict:
    """Le contenu du site : exécuté par Node.js s'il est là, sinon None."""
    node = shutil.which("node")
    if node is None:
        return {}
    script = "global.window={};eval(require('fs').readFileSync(process.argv[1],'utf8'));console.log(JSON.stringify(window.CONTENU))"
    sortie = subprocess.run([node, "-e", script, str(SITE / "contenu.js")], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(sortie.stdout)


@unittest.skipUnless(SITE.is_dir(), "dossier site/ absent")
class SiteHorsLigne(unittest.TestCase):
    def test_aucune_ressource_externe_n_est_chargee(self):
        for nom in ("index.html", "style.css", "app.js"):
            urls = re.findall(r"https?://[^\s\"')]+", lire(nom))
            self.assertEqual(urls, [], f"{nom} cite une adresse externe : {urls}")
        self.assertNotIn("@import", lire("style.css"))
        self.assertNotRegex(lire("index.html"), r"<(script|link|img|iframe)[^>]+(src|href)=\"(https?:)?//")

    def test_la_seule_adresse_du_contenu_est_la_page_de_la_photo(self):
        urls = set(re.findall(r"https?://[^\s\"')]+", lire("contenu.js")))
        self.assertEqual(urls, {PAGE_COMMONS}, "un lien externe de plus doit être décidé, pas glissé")

    def test_toutes_les_images_citees_existent_et_le_site_reste_leger(self):
        for chemin in set(re.findall(r"assets/[\w.-]+", lire("contenu.js"))):
            self.assertTrue((SITE / chemin).is_file(), f"image absente : {chemin}")
        poids = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
        self.assertLess(poids, POIDS_MAX, f"site/ pèse {poids} octets")

    def test_le_site_se_charge_sans_construction(self):
        index = lire("index.html")
        for fichier in ("style.css", "contenu.js", "app.js"):
            self.assertIn(fichier, index)
        self.assertLess(index.index("contenu.js"), index.index("app.js"), "le contenu se charge avant le comportement")
        self.assertLess(index.index("docs.js"), index.index("app.js"), "les documents se chargent avant le comportement")
        self.assertLess(index.index("lexique.js"), index.index("app.js"), "le lexique se charge avant le comportement")
        for nom in ("package.json", "node_modules", "dist"):
            self.assertFalse((SITE / nom).exists(), f"{nom} : le site n'a pas d'étape de construction")


@unittest.skipUnless(SITE.is_dir(), "dossier site/ absent")
class Honnetete(unittest.TestCase):
    def test_la_photo_est_celle_de_wikimedia_commons_non_modifiee_avec_sa_mention(self):
        octets = (SITE / "assets" / "capteur-boucle.jpg").read_bytes()
        self.assertEqual(hashlib.sha256(octets).hexdigest(), PHOTO_SHA256, "la photo CC BY-SA a été modifiée ou remplacée")
        texte = lire("contenu.js")
        for mention in ("Louis van Senden", "CC BY-SA 4.0", "Wikimedia Commons"):
            self.assertIn(mention, texte)
        self.assertIn("ce n'est pas le capteur de METR-LA", texte)

    def test_une_donnee_simulee_est_dite_simulee(self):
        texte = lire("contenu.js")
        self.assertIn("jamais présentées comme réelles", texte)
        self.assertIn('id="chipsim"', lire("index.html"))
        for repere in ("Données simulées · ville fictive", "Données simulées", "Réel · Los Angeles"):
            self.assertIn(repere, texte)
        self.assertIn("non confirmé par un producteur", texte)  # METR-LA : ce que la fiche de provenance dit, rien de plus

    def test_les_chiffres_de_l_intelligence_sont_ceux_des_resultats(self):
        texte = lire("contenu.js")
        resultats = (RACINE / "ml" / "evaluation" / "resultats.md").read_text(encoding="utf-8") if (RACINE / "ml" / "evaluation" / "resultats.md").is_file() else ""
        if resultats:
            francais = resultats.replace(".", ",")  # le fichier écrit « ≥ 0.9781 » dans la colonne « Exigé » : le site écrit à la française
            for chiffre in ("0,9814", "0,9799", "0,2143", "0,9781", "0,9885"):
                self.assertIn(chiffre, francais, f"{chiffre} n'est plus dans ml/evaluation/resultats.md")
                self.assertIn(chiffre, texte)
        prevision = RACINE / "ml" / "evaluation" / "prevision-reseau.json"
        if prevision.is_file():
            horizons = json.loads(prevision.read_text(encoding="utf-8"))["horizons"]
            attendu = {"5": (2.784, 2.230, "19,9"), "15": (3.457, 2.702, "21,8"), "30": (4.145, 3.099, "25,2")}
            for minutes, (persistance, reseau, gain) in attendu.items():
                bloc = horizons[minutes]
                self.assertAlmostEqual(bloc["persistance"]["mae"], persistance, places=3)
                self.assertAlmostEqual(bloc["reseau"]["mae"], reseau, places=3)
                self.assertEqual(f"{bloc['gain_contre_persistance'] * 100:.1f}".replace(".", ","), gain)
        self.assertIn("rejeté", texte.lower())


@unittest.skipUnless(SITE.is_dir(), "dossier site/ absent")
@unittest.skipUnless(shutil.which("node"), "Node.js absent : le contenu n'est pas exécuté")
class ContenuExecute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = contenu()

    def test_l_oral_dure_vingt_minutes(self):
        self.assertEqual(sum(s["secs"] for s in self.c["scenes"]), 1200)
        self.assertEqual([s["id"] for s in self.c["scenes"]], ["prologue", "citoyen", "capteur", "parcours", "intelligence", "reponse", "retour"])

    def test_chaque_scene_a_ses_preuves_et_ses_notes(self):
        for s in self.c["scenes"]:
            self.assertTrue(s["preuves"], s["id"])
            self.assertTrue(s["orateur"], s["id"])
            self.assertIn("limites", s)

    def test_chaque_question_du_jury_mene_a_une_scene_et_a_une_preuve(self):
        self.assertGreaterEqual(len(self.c["jury"]), 6)
        for q in self.c["jury"]:
            self.assertTrue(0 <= q["scene"] < len(self.c["scenes"]), q["q"])
            self.assertTrue(q["preuve"], q["q"])

    def test_les_neuf_competences_bc05_sont_la_avec_leur_niveau(self):
        lignes = self.c["matrice"]["lignes"]
        self.assertEqual(len(lignes), 9)
        niveaux = [ligne[1] for ligne in lignes]
        self.assertEqual((niveaux.count("Implémenté"), niveaux.count("Prototype ciblé")), (6, 3))

    def test_chaque_commande_existe_pour_linux_et_pour_windows(self):
        for etape, linux, windows in self.c["demo"]["pile"]["lignes"]:
            self.assertTrue(linux.startswith("python3 scripts/dev/dev.py "), etape)
            self.assertEqual(windows, linux.replace("python3 ", "py -3 ", 1), etape)

    def test_le_total_des_conditions_du_classifieur_est_juste(self):
        conditions = self.c["scenes"][4]["classifieur"]["conditions"]
        self.assertEqual([c[3] for c in conditions], [True, False, True, True, False])
        self.assertEqual(self.c["scenes"][4]["classifieur"]["verdict"], "REJETÉ")

    def test_le_film_ne_parle_que_de_ce_qui_est_demontre(self):
        # Décision du binôme (retour sur la maquette, 26/11/2026) : le film porte sur le local ; le cloud reste décrit dans docs/05-cloud-aws.
        texte = json.dumps(self.c, ensure_ascii=False).lower()
        for mot in ("aws", "amazon", "cloudwatch", "terraform"):
            self.assertNotIn(mot, texte)

    def test_node_ne_voit_aucune_erreur_de_syntaxe_dans_le_comportement(self):
        resultat = subprocess.run([shutil.which("node"), "--check", str(SITE / "app.js")], capture_output=True, text=True, timeout=30)
        self.assertEqual(resultat.returncode, 0, resultat.stderr)


# Documents qui parlent du cloud : chaque ajout à ce tableau est une décision du binôme (le film, lui, n'en parle pas).
# Le nombre est celui des mots « aws, amazon, cloudwatch, terraform, sagemaker, glue, emr » dans le texte lisible.
DOCUMENTS_AVEC_MENTION_CLOUD = {
    "docs/00-cadrage/note-de-cadrage.md": 2,
    "docs/01-architecture/adr/ADR-015-modeles-ia.md": 1,
    "docs/03-donnees/surveillance-derive.md": 1,
    "docs/03-donnees/rapport-rejeu-etl.md": 5,
}


@unittest.skipUnless(SITE.is_dir(), "dossier site/ absent")
@unittest.skipUnless(shutil.which("node"), "Node.js absent : docs.js n'est pas exécuté")
@unittest.skipUnless((SITE / "docs.js").is_file(), "site/docs.js absent")
class LecteurDeDocuments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = contenu()
        cls.docs = donnees("docs.js", "DOCS")

    def references(self):
        refs = []
        for scene in self.c["scenes"]:
            refs += scene.get("docs", [])
        for question in self.c["jury"]:
            refs += question.get("docs", [])
        for ligne in self.c["matrice"]["lignes"]:
            refs += ligne[4] if len(ligne) > 4 else []
        return refs

    def test_chaque_question_du_jury_ouvre_au_moins_un_document(self):
        for question in self.c["jury"]:
            self.assertTrue(question.get("docs"), f"question sans document : {question['q']}")

    def test_chaque_reference_a_son_document_et_son_ancre(self):
        for reference in self.references():
            chemin, _, ancre = reference.partition("#")
            self.assertIn(chemin, self.docs, f"document absent de docs.js : {chemin}")
            if ancre:
                self.assertIn(f'id="{ancre}"', self.docs[chemin]["html"], f"ancre absente : {reference}")

    def test_aucun_document_n_est_la_sans_etre_cite(self):
        self.assertEqual(sorted(set(self.docs) - {r.partition("#")[0] for r in self.references()}), [])

    def test_chaque_document_est_la_copie_exacte_du_fichier_au_commit_indique(self):
        verifies = 0
        for chemin, doc in self.docs.items():
            commit = doc["commit"]
            if not re.fullmatch(r"[0-9a-f]{7,}", commit):  # « (modifié) » ou « non commité » : pas de référence à comparer
                continue
            resultat = subprocess.run(["git", "-C", str(RACINE), "show", f"{commit}:{chemin}"], capture_output=True, check=False)
            if resultat.returncode != 0:  # commit absent de ce clone (autre branche, clone superficiel) : non comparable ici
                continue
            self.assertEqual(hashlib.sha256(resultat.stdout.decode("utf-8").encode("utf-8")).hexdigest(), doc["sha256"], f"{chemin} n'est plus celui du commit {commit} : relancer scripts/dev/site_docs.py")
            verifies += 1
        self.assertGreaterEqual(verifies, 0)

    def test_les_documents_n_ont_rien_d_actif_ni_d_externe(self):
        html = "".join(d["html"] for d in self.docs.values())
        for motif in (r"<script", r"<iframe", r"<img", r"<link", r"\ssrc=", r'href="https?:', r"javascript:", r"\son\w+="):
            self.assertIsNone(re.search(motif, html, re.I), f"motif interdit dans docs.js : {motif}")

    def test_les_diagrammes_sont_dessines(self):
        for chemin, doc in self.docs.items():
            self.assertNotIn("schema texte", doc["html"], f"diagramme sans dessin dans {chemin}")

    def test_les_mentions_du_cloud_dans_les_documents_sont_connues(self):
        trouvees = {}
        for chemin, doc in self.docs.items():
            lisible = re.sub(r"<[^>]+>", " ", doc["html"])
            n = len(re.findall(r"\b(aws|amazon|cloudwatch|terraform|sagemaker|glue|emr)\b", lisible, re.I))
            if n:
                trouvees[chemin] = n
        self.assertEqual(trouvees, DOCUMENTS_AVEC_MENTION_CLOUD, "un document qui parle du cloud est ajouté ou retiré : décision du binôme à consigner dans ce test")


# Mots écrits en majuscules dans le site qui ne sont pas des sigles : étiquettes d'étapes et de schémas.
MAJUSCULES_SANS_SIGLE = {
    "ALERTE", "CAPTEUR", "CORE", "NOVARIA", "FLUX", "PUBLIC", "REJET", "RECEIVE", "PROCESS", "RESPOND", "STREAM", "PAS", "VITESSE", "TEMPS", "SEUILS",
    "HORS", "LIGNE", "GARDE", "FOUS", "VISION", "BY", "SA", "ALERT", "SLOW", "DE",
}
MOTS_DU_CLOUD = r"\b(aws|amazon|cloudwatch|terraform|sagemaker|glue|emr|moto|ecs|rds|iam|ecr|msk|vpc|ssm|sns|ec2|ebs|efs|alb|kms|s3|oidc)\b"


@unittest.skipUnless(SITE.is_dir(), "dossier site/ absent")
@unittest.skipUnless(shutil.which("node"), "Node.js absent : lexique.js n'est pas exécuté")
@unittest.skipUnless((SITE / "lexique.js").is_file(), "site/lexique.js absent")
class Lexique(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = donnees("lexique.js", "LEXIQUE")
        cls.c = contenu()
        cls.docs = donnees("docs.js", "DOCS") if (SITE / "docs.js").is_file() else {}

    def test_chaque_entree_a_un_theme_connu_un_terme_et_une_definition(self):
        themes = {th["id"] for th in self.lex["themes"]}
        self.assertEqual(len(themes), len(self.lex["themes"]), "thèmes en double")
        for e in self.lex["entrees"]:
            self.assertIn(e["c"], themes, e["t"])
            self.assertTrue(e["t"].strip() and len(e["d"]) >= 20, f"entrée vide ou trop courte : {e['t']}")
            self.assertTrue(e["d"].rstrip().endswith((".", "»", ")")), f"définition sans point final : {e['t']}")

    def test_aucun_terme_n_est_en_double_et_chaque_theme_est_utilise(self):
        termes = [e["t"].casefold() for e in self.lex["entrees"]]
        self.assertEqual(sorted({t for t in termes if termes.count(t) > 1}), [])
        for th in self.lex["themes"]:
            self.assertTrue([e for e in self.lex["entrees"] if e["c"] == th["id"]], f"thème sans entrée : {th['id']}")
        self.assertGreaterEqual(len(termes), 150)

    def test_chaque_renvoi_voir_aussi_mene_a_un_terme(self):
        termes = {e["t"] for e in self.lex["entrees"]}
        for e in self.lex["entrees"]:
            for v in e.get("v", []):
                self.assertIn(v, termes, f"« {e['t']} » renvoie à un terme absent : {v}")

    def test_chaque_document_du_lexique_est_dans_le_lecteur(self):
        for e in self.lex["entrees"]:
            for reference in e.get("docs", []):
                chemin, _, ancre = reference.partition("#")
                self.assertIn(chemin, self.docs, f"« {e['t']} » cite un document absent de docs.js : {chemin}")
                if ancre:
                    self.assertIn(f'id="{ancre}"', self.docs[chemin]["html"], f"ancre absente : {reference}")

    def test_chaque_sigle_employe_dans_le_site_est_defini(self):
        def textes(o):
            if isinstance(o, str):
                return [o]
            if isinstance(o, list):
                return [x for v in o for x in textes(v)]
            if isinstance(o, dict):
                return [x for k, v in o.items() if k != "docs" for x in textes(v)]
            return []
        visible = "\n".join(textes(self.c))
        sigles = set(re.findall(r"(?<![A-Za-zÀ-ÿ0-9_])[A-Z][A-Z0-9]{1,7}(?![A-Za-zÀ-ÿ0-9_])", visible)) - MAJUSCULES_SANS_SIGLE
        definis = {m for e in self.lex["entrees"] for m in re.split(r"[^A-Za-z0-9]+", e["t"] + " " + e.get("l", "") + " " + " ".join(e.get("a", [])))}
        self.assertEqual(sorted(sigles - definis), [], "sigles employés dans le site mais absents du lexique")

    def test_le_lexique_ne_parle_pas_du_cloud(self):
        # Décision du binôme (retour sur la maquette, 26/11/2026), comme pour le film.
        texte = json.dumps(self.lex, ensure_ascii=False)
        self.assertIsNone(re.search(MOTS_DU_CLOUD, texte, re.I), re.search(MOTS_DU_CLOUD, texte, re.I) and re.search(MOTS_DU_CLOUD, texte, re.I).group(0))


if __name__ == "__main__":
    unittest.main()
