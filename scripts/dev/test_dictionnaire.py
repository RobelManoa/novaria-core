"""Complétude du dictionnaire de données (issues DAT-02 et DAT-10) : bibliothèque standard seulement.

Critère d'acceptation : le dictionnaire est complet. Ce test compare docs/03-donnees/dictionnaire-de-donnees.md à ce que
créent réellement les scripts :
- PostgreSQL : chaque table et chaque colonne des migrations de db/postgres/migrations/ est décrite, ainsi que chaque
  valeur des listes `IN (...)` des contraintes ;
- MongoDB (si Node.js est installé) : le script db/mongo/init/ est exécuté avec une base simulée ; chaque collection a sa
  section, chaque champ (chemin pointé), son caractère obligatoire, chaque valeur d'énumération et chaque index y figurent.

Limite : une colonne est cherchée dans tout le dictionnaire, pas dans le tableau de sa seule table.
Lancement : python3 -m unittest discover -s scripts/dev -p "test_dictionnaire.py"   (Windows : py -3 ...)
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
DICTIONNAIRE = RACINE / "docs" / "03-donnees" / "dictionnaire-de-donnees.md"
BASES_LOCALES = RACINE / "docs" / "03-donnees" / "base-de-donnees-locale.md"
MIGRATIONS = RACINE / "db" / "postgres" / "migrations"
INIT_MONGO = RACINE / "db" / "mongo" / "init" / "01-collections-et-utilisateurs.js"

# Exécute le script d'initialisation avec une base simulée et affiche ce qu'il crée.
EXTRACTION_MONGO = r"""
const fs = require("fs");
const sortie = { collections: {}, index: {} };
const base = new Proxy({}, {
  get(_, nom) {
    if (nom === "createCollection") return (n, options) => { sortie.collections[n] = options.validator.$jsonSchema; };
    if (nom === "createRole" || nom === "createUser") return () => {};
    return { createIndex: (cles, options) => { (sortie.index[nom] = sortie.index[nom] || []).push(options.name); } };
  },
});
new Function("db", "print", fs.readFileSync(process.argv[2], "utf8"))({ getSiblingDB: () => base }, () => {});
console.log(JSON.stringify(sortie));
"""
ENVIRONNEMENT_MONGO = {
    "MONGO_DB": "novaria",
    **{f"MONGO_PASSWORD_{nom}": "x" for nom in ("COLLECTE", "TRAITEMENT", "REPONSE", "BACKEND", "ML")},
}


def texte_du_dictionnaire() -> str:
    return DICTIONNAIRE.read_text(encoding="utf-8")


def jetons(texte: str) -> set[str]:
    """Mots entre apostrophes inverses, hors blocs de code (les diagrammes ne comptent pas comme description)."""
    sans_blocs = re.sub(r"```.*?```", "", texte, flags=re.S)
    resultat = set()
    for brut in re.findall(r"`([^`\n]+)`", sans_blocs):
        resultat.add(brut)
        resultat.update(morceau for morceau in re.split(r"[\s,.]+", brut) if morceau)
    return resultat


def tables_sql():
    """(schéma, table, colonnes) pour chaque CREATE TABLE des migrations."""
    for fichier in sorted(MIGRATIONS.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", fichier.read_text(encoding="utf-8"))
        for entete in re.finditer(r"CREATE TABLE (\w+)\.(\w+) \(", sql):
            profondeur, fin = 1, entete.end()
            while profondeur:
                profondeur += (sql[fin] == "(") - (sql[fin] == ")")
                fin += 1
            elements, courant, niveau = [], "", 0
            for caractere in sql[entete.end() : fin - 1]:
                niveau += (caractere == "(") - (caractere == ")")
                if caractere == "," and niveau == 0:
                    elements.append(courant)
                    courant = ""
                else:
                    courant += caractere
            elements.append(courant)
            colonnes = [e.split()[0] for e in elements if e.split() and e.split()[0].upper() not in {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"}]
            yield entete.group(1), entete.group(2), colonnes


def valeurs_in_sql() -> set[str]:
    valeurs = set()
    for fichier in MIGRATIONS.glob("*.sql"):
        sql = re.sub(r"--[^\n]*", "", fichier.read_text(encoding="utf-8"))
        for liste in re.findall(r"\bIN \(((?:'[^']*'(?:,\s*)?)+)\)", sql):
            valeurs.update(re.findall(r"'([^']*)'", liste))
    return valeurs


class DictionnairePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jetons = jetons(texte_du_dictionnaire())
        cls.tables = list(tables_sql())

    def test_les_migrations_creent_des_tables(self):
        self.assertGreaterEqual(len(self.tables), 12)

    def test_chaque_table_est_decrite(self):
        manquantes = [f"{s}.{t}" for s, t, _ in self.tables if t not in self.jetons]
        self.assertEqual(manquantes, [], "Tables des migrations absentes du dictionnaire")

    def test_chaque_colonne_est_decrite(self):
        manquantes = [f"{t}.{c}" for _, t, colonnes in self.tables for c in colonnes if c not in self.jetons]
        self.assertEqual(manquantes, [], "Colonnes des migrations absentes du dictionnaire")

    def test_chaque_valeur_d_enumeration_est_citee(self):
        texte = texte_du_dictionnaire()
        manquantes = sorted(v for v in valeurs_in_sql() if not re.search(rf"(?<![\w]){re.escape(v)}(?![\w])", texte))
        self.assertEqual(manquantes, [], "Valeurs autorisées par une contrainte mais absentes du dictionnaire")

    def test_les_tables_sont_aussi_dans_le_document_des_bases_locales(self):
        texte = BASES_LOCALES.read_text(encoding="utf-8")
        manquantes = [f"{s}.{t}" for s, t, _ in self.tables if s in {"dwh", "alertes"} and f"`{t}`" not in texte]
        self.assertEqual(manquantes, [])

    def test_aucun_secret_ni_donnee_personnelle_dans_le_dictionnaire(self):
        texte = texte_du_dictionnaire()
        self.assertNotRegex(texte, r"(?i)(password|mot de passe)\s*[:=]\s*['\"`]\S{6,}")
        self.assertNotRegex(texte, r"[\w.+-]+@[\w-]+\.[\w.]+")


def champs(schema: dict, prefixe: str = ""):
    """(chemin pointé, obligatoire, valeurs d'énumération) pour chaque champ d'un validateur $jsonSchema."""
    obligatoires = set(schema.get("required", []))
    for nom in list(schema.get("properties", {})) + [n for n in obligatoires if n not in schema.get("properties", {})]:
        sous = schema.get("properties", {}).get(nom, {})
        chemin = f"{prefixe}{nom}"
        yield chemin, nom in obligatoires, sous.get("enum", [])
        yield from champs(sous, f"{chemin}.")


@unittest.skipIf(shutil.which("node") is None, "Node.js absent : la partie MongoDB n'est pas contrôlée")
class DictionnaireMongo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as dossier:
            script = Path(dossier) / "extraire.js"
            script.write_text(EXTRACTION_MONGO, encoding="utf-8")
            resultat = subprocess.run(
                ["node", str(script), str(INIT_MONGO)],
                capture_output=True, text=True, encoding="utf-8", timeout=60,
                env={**os.environ, **ENVIRONNEMENT_MONGO},
            )
        if resultat.returncode != 0:
            raise AssertionError(f"Le script d'initialisation MongoDB a échoué :\n{resultat.stderr}")
        cls.mongo = json.loads(resultat.stdout)
        texte = texte_du_dictionnaire()
        debut = texte.index("## 10. Collections MongoDB")
        fin = texte.index("\n## ", debut + 1)
        cls.sections = {}
        for correspondance in re.finditer(r"^### 10\.\d+ `(\w+)`\n(.*?)(?=^### |\Z)", texte[debut:fin] + "\n### fin", re.S | re.M):
            cls.sections[correspondance.group(1)] = correspondance.group(2)

    def test_le_script_cree_six_collections(self):
        self.assertEqual(len(self.mongo["collections"]), 6)

    def test_chaque_collection_a_sa_section(self):
        self.assertEqual(sorted(self.sections), sorted(self.mongo["collections"]))

    def test_chaque_champ_est_decrit_avec_son_caractere_obligatoire(self):
        for collection, schema in self.mongo["collections"].items():
            lignes = {}
            for ligne in self.sections[collection].splitlines():
                cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
                correspondance = re.fullmatch(r"`([\w.]+)`", cellules[0]) if ligne.startswith("|") and len(cellules) >= 5 else None
                if correspondance:
                    lignes[correspondance.group(1)] = cellules[2]
            for chemin, obligatoire, _ in champs(schema):
                with self.subTest(collection=collection, champ=chemin):
                    self.assertIn(chemin, lignes, "champ absent du dictionnaire")
                    self.assertEqual(lignes[chemin], "oui" if obligatoire else "non")

    def test_chaque_enumeration_est_citee(self):
        for collection, schema in self.mongo["collections"].items():
            for chemin, _, valeurs in champs(schema):
                for valeur in valeurs:
                    with self.subTest(collection=collection, champ=chemin, valeur=valeur):
                        self.assertRegex(self.sections[collection], rf"(?<!\w){re.escape(valeur)}(?!\w)")

    def test_chaque_index_est_decrit(self):
        for collection, noms in self.mongo["index"].items():
            for nom in noms:
                with self.subTest(collection=collection, index=nom):
                    self.assertIn(f"`{nom}`", self.sections[collection])


if __name__ == "__main__":
    unittest.main()
