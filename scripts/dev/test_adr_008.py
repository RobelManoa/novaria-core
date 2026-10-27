"""Contrôle de l'ADR-008, architecture en microservices (issue MS-01) : bibliothèque standard seulement.

Critère d'acceptation : l'ADR contient problème, options (monolithe modulaire ou quatre services), choix et conséquences.
Ce test vérifie aussi que le tableau « une base logique par service » (section 4.4) décrit bien les droits créés par
db/postgres/init/ et db/mongo/init/ : l'ADR ne peut pas dériver des scripts.
La partie MongoDB demande Node.js ; sans lui, elle est ignorée.

Ne contrôle pas la validation du professeur : elle est demandée en section 9 et reste à consigner.
Lancement : python3 -m unittest discover -s scripts/dev -p "test_adr_008.py"   (Windows : py -3 ...)
"""
import re
import shutil
import unittest
from pathlib import Path

from test_dictionnaire import extraire_mongo

RACINE = Path(__file__).resolve().parents[2]
ADR = RACINE / "docs" / "01-architecture" / "adr" / "ADR-008-microservices.md"
INIT_POSTGRES = RACINE / "db" / "postgres" / "init" / "01-roles-et-schemas.sh"
REGISTRE_RISQUES = RACINE / "docs" / "07-gestion" / "registre-risques.md"
ACTIONS = {"lire": "find", "insérer": "insert", "modifier": "update"}
SERVICES = ["Collecte", "Traitement", "Alerte usager", "Réponse extérieure"]


def texte() -> str:
    return ADR.read_text(encoding="utf-8")


def section(titre: str) -> str:
    """Texte d'une section « ## ... » ou « ### ... », jusqu'au titre de même niveau ou supérieur."""
    contenu = texte()
    debut = contenu.index(titre)
    niveau = len(titre) - len(titre.lstrip("#"))
    suite = re.search(rf"^#{{1,{niveau}}} ", contenu[debut + len(titre) :], re.M)
    return contenu[debut : debut + len(titre) + suite.start()] if suite else contenu[debut:]


def lignes_du_tableau_4_4() -> dict[str, list[str]]:
    """Propriétaire -> [cellule PostgreSQL, cellule MongoDB] du premier tableau de la section 4.4."""
    resultat, commence = {}, False
    for ligne in section("### 4.4 Une base logique par service").splitlines():
        if not ligne.startswith("|"):
            if commence:
                break  # fin du premier tableau
            continue
        commence = True
        if not ligne.startswith(("| Propriétaire", "|---")):
            cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
            resultat[cellules[0]] = cellules[1:]
    return resultat


def droits_declares(cellule: str) -> tuple[str, dict[str, set[str]]]:
    """« `a`, `b` : lire, insérer ; `c` : lire (`svc_x`) » -> ('svc_x', {'a': {...}, 'b': {...}, 'c': {...}})."""
    compte = re.search(r"\(`(svc_\w+)`\)\s*$", cellule)
    droits = {}
    for segment in cellule.split(";"):
        morceau = re.match(r"\s*(`[^:]+?)\s*:\s*([^()]+)", segment)
        if morceau:
            actions = {ACTIONS[a.strip()] for a in morceau.group(2).split(",")}
            for collection in re.findall(r"`(\w+)`", morceau.group(1)):
                droits[collection] = actions
    return (compte.group(1) if compte else ""), droits


class StructureDeLAdr(unittest.TestCase):
    def test_les_sections_attendues_sont_presentes(self):
        for titre in ("## 1. Problème", "## 2. Forces de décision", "## 3. Options comparées", "## 4. Choix",
                      "## 5. Conséquences", "## 6. Plan de repli", "## 7. Vérification", "## 9. Validation par le professeur"):
            with self.subTest(titre=titre):
                self.assertIn(titre, texte())

    def test_les_options_comparent_le_monolithe_modulaire_et_les_quatre_services(self):
        options = section("## 3. Options comparées")
        self.assertRegex(options, r"\| B\. Monolithe modulaire .*Plan de repli")
        self.assertRegex(options, r"\| \*\*C\. Quatre microservices .*\*\*Retenue\*\*")

    def test_le_decoupage_nomme_les_quatre_services(self):
        decoupage = section("### 4.1 Découpage")
        for service in SERVICES:
            with self.subTest(service=service):
                self.assertIn(f"| **{service}**", decoupage)

    def test_chaque_service_a_une_architecture_interne_et_sa_raison(self):
        interne = section("### 4.5 Architecture interne de chaque service et raison du choix")
        for service in SERVICES:
            ligne = next((l for l in interne.splitlines() if l.startswith(f"| **{service}**")), "")
            with self.subTest(service=service):
                cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
                self.assertEqual(len(cellules), 4)
                self.assertTrue(all(len(c) > 30 for c in cellules[1:]), "architecture, raison ou compromis absent")

    def test_les_trois_risques_demandes_sont_listes_avec_leur_parade(self):
        risques = section("## 5. Conséquences")
        for mot in ("Complexité d'exploitation", "Délai du 10/12/2026", "Coût AWS"):
            with self.subTest(risque=mot):
                ligne = next((l for l in risques.splitlines() if l.startswith(f"| **{mot}")), "")
                self.assertTrue(ligne, "risque absent")
                self.assertGreaterEqual(len([c for c in ligne.split("|") if c.strip()]), 5)

    def test_les_risques_du_registre_cites_existent(self):
        registre = REGISTRE_RISQUES.read_text(encoding="utf-8")
        cites = set(re.findall(r"\bR(\d+)\b", section("## 5. Conséquences")))
        self.assertTrue(cites)
        for numero in cites:
            with self.subTest(risque=f"R{numero}"):
                self.assertRegex(registre, rf"(?m)^\| R{numero} \|")

    def test_la_validation_du_professeur_n_est_pas_affirmee_sans_trace(self):
        """Tant que decisions-professeur.md ne consigne pas la validation, l'ADR doit dire qu'elle manque."""
        decisions = (RACINE / "docs" / "07-gestion" / "decisions-professeur.md").read_text(encoding="utf-8")
        validee = re.search(r"(?i)microservices|quatre services|découpage", decisions)
        if not validee:
            self.assertIn("non obtenue", texte())
            self.assertIn("non validée", section("## 9. Validation par le professeur"))

    def test_les_liens_relatifs_se_resolvent(self):
        for cible in re.findall(r"\]\(([^)\s]+)\)", texte()):
            if cible.startswith(("http", "#")):
                continue
            with self.subTest(lien=cible):
                self.assertTrue((ADR.parent / cible.split("#")[0]).exists())


class BasesLogiques(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tableau = lignes_du_tableau_4_4()
        cls.init_postgres = INIT_POSTGRES.read_text(encoding="utf-8")

    def test_le_tableau_couvre_les_quatre_services_et_les_deux_composants_voisins(self):
        attendus = SERVICES + ["API métier (hors des quatre services)", "Module d'apprentissage (hors des quatre services)"]
        self.assertEqual(sorted(self.tableau), sorted(attendus))

    def test_les_schemas_postgresql_de_l_adr_ont_leur_compte_dans_le_script(self):
        attendu = {"Traitement": ("dwh", "svc_traitement"), "Alerte usager": ("alertes", "svc_alerte")}
        for proprietaire, (schema, compte) in attendu.items():
            with self.subTest(proprietaire=proprietaire):
                self.assertIn(f"`{schema}`", self.tableau[proprietaire][0])
                self.assertIn(f"(`{compte}`)", self.tableau[proprietaire][0])
                self.assertRegex(
                    self.init_postgres,
                    rf"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {compte};",
                )
        self.assertIn("(`svc_app`)", self.tableau["API métier (hors des quatre services)"][0])
        self.assertRegex(self.init_postgres, r"GRANT USAGE, CREATE ON SCHEMA app TO svc_app;")

    def test_les_services_sans_postgresql_n_ont_pas_de_compte_dedie(self):
        for proprietaire in ("Collecte", "Réponse extérieure"):
            with self.subTest(proprietaire=proprietaire):
                self.assertEqual(self.tableau[proprietaire][0], "aucun")
        self.assertNotRegex(self.init_postgres, r"CREATE ROLE svc_(collecte|reponse)")

    def test_svc_lecture_ne_peut_que_lire(self):
        self.assertRegex(self.init_postgres, r"ALTER DEFAULT PRIVILEGES IN SCHEMA dwh GRANT SELECT ON TABLES TO svc_lecture;")
        self.assertRegex(self.init_postgres, r"ALTER DEFAULT PRIVILEGES IN SCHEMA alertes GRANT SELECT ON TABLES TO svc_lecture;")


@unittest.skipIf(shutil.which("node") is None, "Node.js absent : la partie MongoDB n'est pas contrôlée")
class DroitsMongo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mongo = extraire_mongo()
        cls.reels = {}
        for utilisateur, roles in mongo["utilisateurs"].items():
            droits = {}
            for role in roles:
                for privilege in mongo["roles"][role]:
                    droits.setdefault(privilege["resource"]["collection"], set()).update(privilege["actions"])
            cls.reels[utilisateur] = droits
        cls.tableau = lignes_du_tableau_4_4()

    def test_les_droits_mongodb_de_l_adr_sont_ceux_du_script(self):
        for proprietaire, (_, cellule) in self.tableau.items():
            if cellule == "aucune":
                continue
            compte, declares = droits_declares(cellule)
            with self.subTest(proprietaire=proprietaire, compte=compte):
                self.assertIn(compte, self.reels, "compte inconnu du script")
                self.assertEqual(declares, self.reels[compte])

    def test_les_services_sans_mongodb_n_ont_pas_de_compte(self):
        self.assertEqual(self.tableau["Alerte usager"][1], "aucune")
        self.assertNotIn("svc_alerte", self.reels)


if __name__ == "__main__":
    unittest.main()
