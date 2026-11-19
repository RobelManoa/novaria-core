"""Aucun SDK AWS dans le code (ADR-023 règle 2, ADR-025 règle 1, LOC-05) : ce test échoue si `boto3` ou un autre kit de
développement AWS est importé, déclaré comme dépendance ou installé par un script.

Le dépôt n'a pas de dossier `backend/` : les services sont dans `services/`. Le test regarde donc tout le code qui peut
parler à un service : `services/`, `ml/`, `simulator/`, `data/`, `automation/`, `gateway/`, `scripts/` et `frontend/`
(sources et `package.json`). Il ne regarde ni `infra/` (Terraform nomme le fournisseur AWS, cible documentée), ni
`.github/` (`deploy.yml`, inactif), ni `docs/` (qui parle d'AWS), ni les chaînes de caractères : écrire « boto3 » dans un
texte n'est pas l'importer.

Le jour où AWS sera autorisé par écrit (ADR-023, règle 8), l'adaptateur S3 sera le seul module à pouvoir importer un
SDK : cette exception se déclarera ici, dans `EXCEPTIONS`, avec son ADR.

Bibliothèque standard seulement. Lancement : python3 -m unittest tests.test_absence_sdk_aws   (Windows : py -3 ...)
"""

import ast
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
DOSSIERS_SURVEILLES = ("services", "ml", "simulator", "data", "automation", "gateway", "scripts", "frontend")
DOSSIERS_IGNORES = {"venv", ".venv", "node_modules", "__pycache__", ".git", "dist", "build", "coverage", ".mypy_cache", ".pytest_cache", "site-packages"}
EXCEPTIONS: frozenset[str] = frozenset()  # chemins relatifs (avec « / ») autorisés à importer un SDK ; vide : aucune

# Modules et paquets Python des SDK et outils AWS (noms normalisés : minuscules, « _ » pour « - » et « . »).
PYTHON_EXACTS = {
    "boto", "boto3", "botocore", "aioboto3", "aiobotocore", "s3transfer", "s3fs", "awscli", "awswrangler", "aws_lambda_powertools",
    "aws_xray_sdk", "sagemaker", "pyathena", "redshift_connector", "localstack", "moto", "chalice", "zappa",
}
PYTHON_PREFIXES = ("aws_cdk", "mypy_boto3", "types_boto3", "types_aiobotocore", "boto3_stubs", "botocore_stubs", "aws_sam")
# Paquets JavaScript.
JS_EXACTS = {"aws-sdk", "aws-cdk-lib", "aws-cdk", "aws-amplify", "aws-lambda", "aws-xray-sdk", "aws-serverless-express"}
JS_PREFIXES = ("@aws-sdk/", "@aws-cdk/", "@smithy/", "@aws-amplify/", "@aws-lambda-powertools/")

EXTENSIONS_JS = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}
FICHIERS_EXIGENCES = re.compile(r"(requirements[^/]*\.(txt|in)|constraints[^/]*\.txt)$")
FICHIERS_SCRIPTS = re.compile(r"(Dockerfile[^/]*|[^/]+\.(sh|ps1|bat)|Makefile)$")
IMPORT_JS = re.compile(r"""(?:\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(\s*|\bimport\s+)["']([^"']+)["']""")
IMPORT_PYTHON_REPLI = re.compile(r"^\s*(?:from|import)\s+([A-Za-z0-9_.]+)", re.M)  # fichier qui ne s'analyse pas
INSTALLATION = re.compile(r"\b(?:pip3?|python3?\s+-m\s+pip|npm|pnpm|yarn)\s+(?:install|add|i)\b([^\n\\&|;]*)")


def nom_python(nom: str) -> str:
    return re.split(r"[<>=!~\[;@ ]", nom.strip(), maxsplit=1)[0].lower().replace("-", "_").replace(".", "_")


def est_sdk_python(nom: str) -> bool:
    nom = nom_python(nom)
    return nom in PYTHON_EXACTS or nom.startswith(PYTHON_PREFIXES)


def est_sdk_js(nom: str) -> bool:
    nom = nom.strip().lower()
    return nom in JS_EXACTS or nom.startswith(JS_PREFIXES)


def imports_python(source: str) -> list[tuple[int, str]]:
    """(ligne, module) de chaque importation, y compris `__import__("x")` et `importlib.import_module("x")` à nom constant."""
    try:
        arbre = ast.parse(source)
    except (SyntaxError, ValueError):
        return [(source.count("\n", 0, m.start()) + 1, m.group(1)) for m in IMPORT_PYTHON_REPLI.finditer(source)]
    trouves: list[tuple[int, str]] = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            trouves += [(noeud.lineno, alias.name) for alias in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
            trouves.append((noeud.lineno, noeud.module))  # « from . import x » est local, jamais un SDK
        elif isinstance(noeud, ast.Call) and noeud.args and isinstance(noeud.args[0], ast.Constant) and isinstance(noeud.args[0].value, str):
            fonction = noeud.func
            appelee = fonction.attr if isinstance(fonction, ast.Attribute) else getattr(fonction, "id", "")
            if appelee in ("__import__", "import_module"):
                trouves.append((noeud.lineno, noeud.args[0].value))
    return trouves


def dependances_package_json(texte: str) -> list[str]:
    try:
        contenu = json.loads(texte)
    except ValueError:
        return []
    noms: list[str] = []
    for groupe in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        valeurs = contenu.get(groupe) if isinstance(contenu, dict) else None
        if isinstance(valeurs, dict):
            noms += list(valeurs)
    return noms


def dependances_pyproject(texte: str) -> list[tuple[int, str]]:
    """Paquets cités dans les tableaux de dépendances d'un `pyproject.toml` (lecture simple, sans bibliothèque TOML)."""
    trouves = []
    for numero, ligne in enumerate(texte.splitlines(), 1):
        for citation in re.findall(r"""["']([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:[<>=!~\[;@][^"']*)?["']""", ligne):
            if est_sdk_python(citation):
                trouves.append((numero, citation))
    return trouves


def analyser(chemin: Path, racine: Path) -> list[str]:
    """Les violations d'un fichier, une ligne de texte chacune (« chemin:ligne: raison »)."""
    relatif = chemin.relative_to(racine).as_posix()
    if relatif in EXCEPTIONS:
        return []
    try:
        texte = chemin.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    nom = chemin.name
    violations: list[str] = []

    def signaler(ligne: int, raison: str) -> None:
        violations.append(f"{relatif}:{ligne}: {raison}")

    if chemin.suffix == ".py":
        for ligne, module in imports_python(texte):
            if est_sdk_python(module.split(".")[0]):
                signaler(ligne, f"importe {module}")
    elif chemin.suffix in EXTENSIONS_JS:
        for correspondance in IMPORT_JS.finditer(texte):
            if est_sdk_js(correspondance.group(1)):
                signaler(texte.count("\n", 0, correspondance.start()) + 1, f"importe {correspondance.group(1)}")
    if nom == "package.json":
        for paquet in dependances_package_json(texte):
            if est_sdk_js(paquet):
                signaler(1, f"dépend de {paquet}")
    if nom in ("pyproject.toml", "Pipfile", "setup.cfg", "setup.py"):
        for ligne, paquet in dependances_pyproject(texte):
            signaler(ligne, f"dépend de {paquet}")
    if FICHIERS_EXIGENCES.fullmatch(nom):
        for numero, ligne in enumerate(texte.splitlines(), 1):
            declaration = ligne.split("#", 1)[0].strip()
            if declaration and not declaration.startswith("-") and est_sdk_python(declaration):
                signaler(numero, f"dépend de {nom_python(declaration)}")
    if FICHIERS_SCRIPTS.fullmatch(nom):
        for correspondance in INSTALLATION.finditer(texte):
            for mot in correspondance.group(1).split():
                if not mot.startswith("-") and (est_sdk_python(mot) or est_sdk_js(mot)):
                    signaler(texte.count("\n", 0, correspondance.start()) + 1, f"installe {mot}")
    return violations


def chercher_les_sdk_aws(racine: Path = RACINE, dossiers: tuple[str, ...] = DOSSIERS_SURVEILLES) -> list[str]:
    violations: list[str] = []
    for dossier in dossiers:
        debut = racine / dossier
        if not debut.is_dir():
            continue
        for repertoire, sous_dossiers, fichiers in os.walk(debut):
            sous_dossiers[:] = sorted(d for d in sous_dossiers if d not in DOSSIERS_IGNORES)
            for fichier in sorted(fichiers):
                violations += analyser(Path(repertoire) / fichier, racine)
    return violations


class AucunSdkAwsDansLeDepot(unittest.TestCase):
    def test_le_depot_n_importe_ni_ne_declare_aucun_sdk_aws(self):
        self.assertEqual(chercher_les_sdk_aws(), [], "SDK AWS trouvé : le code reste local (ADR-023 règle 2, ADR-025 règle 1)")

    def test_les_dossiers_surveilles_existent(self):
        for dossier in ("services", "ml", "simulator", "frontend"):
            self.assertTrue((RACINE / dossier).is_dir(), f"{dossier}/ n'existe pas : le test ne surveillerait rien")
        self.assertTrue(any((RACINE / "services").glob("*/app")), "aucun service trouvé")


class DetectionDesSdk(unittest.TestCase):
    """Le détecteur voit les formes d'importation courantes et ne crie pas au loup."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.racine = Path(self._tmp.name)

    def ecrire(self, chemin: str, texte: str) -> None:
        cible = self.racine / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(texte, encoding="utf-8")

    def trouver(self) -> list[str]:
        return chercher_les_sdk_aws(self.racine, ("ml", "services", "frontend", "scripts"))

    def test_un_depot_sans_sdk_est_propre(self):
        self.ecrire("ml/src/a.py", "import json\nfrom pathlib import Path\nfrom . import boto3_local\nfrom .boto3 import x\n")
        self.assertEqual(self.trouver(), [])

    def test_les_formes_d_importation_python(self):
        cas = {
            "ml/a.py": "import boto3\n",
            "ml/b.py": "from boto3.session import Session\n",
            "ml/c.py": "import botocore.exceptions as e\n",
            "ml/d.py": "import os, aiobotocore\n",
            "ml/e.py": "x = __import__('boto3')\n",
            "ml/f.py": "import importlib\ny = importlib.import_module('s3fs')\n",
            "ml/g.py": "def f():\n    import sagemaker\n",
            "ml/h.py": "try:\n    import mypy_boto3_s3\nexcept ImportError:\n    pass\n",
        }
        for chemin, source in cas.items():
            self.ecrire(chemin, source)
        trouves = self.trouver()
        self.assertEqual(sorted(v.split(":")[0] for v in trouves), sorted(cas), trouves)

    def test_le_numero_de_ligne_est_donne(self):
        self.ecrire("ml/a.py", "import json\n\nimport boto3\n")
        self.assertEqual(self.trouver(), ["ml/a.py:3: importe boto3"])

    def test_une_chaine_un_commentaire_ou_un_nom_voisin_ne_sont_pas_des_importations(self):
        self.ecrire(
            "ml/a.py",
            '"""Pas de boto3 ici."""\n# import boto3\ntexte = "import boto3"\nimport boto3_non_aws_x\nimport botox\nimport moto_local\n',
        )
        self.assertEqual(self.trouver(), [])

    def test_un_fichier_qui_ne_s_analyse_pas_est_lu_ligne_a_ligne(self):
        self.ecrire("ml/a.py", "def f(:\nimport boto3\n")
        self.assertEqual(self.trouver(), ["ml/a.py:2: importe boto3"])

    def test_les_dependances_declarees(self):
        self.ecrire("services/x/requirements.txt", "fastapi==0.1\nboto3==1.0 --hash=sha256:abc\nBoto3-stubs[s3]>=1\n# boto3\n-r autre.txt\n")
        self.ecrire("services/x/requirements-dev.in", "pytest\nawscli\n")
        self.ecrire("services/x/pyproject.toml", '[project]\ndependencies = ["httpx>=0.2", "botocore~=1.3"]\n')
        trouves = self.trouver()
        self.assertEqual(
            sorted(trouves),
            sorted([
                "services/x/requirements.txt:2: dépend de boto3",
                "services/x/requirements.txt:3: dépend de boto3_stubs",
                "services/x/requirements-dev.in:2: dépend de awscli",
                "services/x/pyproject.toml:2: dépend de botocore",
            ]),
        )

    def test_javascript_et_package_json(self):
        self.ecrire("frontend/src/a.ts", 'import { S3 } from "@aws-sdk/client-s3";\nconst b = require("aws-sdk");\nimport x from "./aws-local";\n')
        self.ecrire("frontend/package.json", json.dumps({"dependencies": {"react": "19", "@aws-sdk/client-s3": "3"}, "devDependencies": {"aws-cdk-lib": "2"}}))
        trouves = self.trouver()
        self.assertIn("frontend/src/a.ts:1: importe @aws-sdk/client-s3", trouves)
        self.assertIn("frontend/src/a.ts:2: importe aws-sdk", trouves)
        self.assertIn("frontend/package.json:1: dépend de @aws-sdk/client-s3", trouves)
        self.assertIn("frontend/package.json:1: dépend de aws-cdk-lib", trouves)
        self.assertEqual(len(trouves), 4, trouves)

    def test_une_installation_dans_un_script_ou_un_dockerfile(self):
        self.ecrire("services/x/Dockerfile", "FROM python:3.12\nRUN pip install --no-cache-dir fastapi boto3\n")
        self.ecrire("scripts/installer.sh", "python3 -m pip install -r r.txt && npm install @aws-sdk/client-s3\n")
        self.ecrire("scripts/propre.sh", "pip install fastapi httpx\n")
        trouves = self.trouver()
        self.assertEqual(sorted(trouves), ["scripts/installer.sh:1: installe @aws-sdk/client-s3", "services/x/Dockerfile:2: installe boto3"])

    def test_les_dossiers_d_environnements_sont_ignores(self):
        self.ecrire("ml/.venv/lib/site-packages/boto3/__init__.py", "import botocore\n")
        self.ecrire("frontend/node_modules/x/index.js", 'require("aws-sdk")\n')
        self.assertEqual(self.trouver(), [])

    def test_une_exception_declaree_est_permise_pour_ce_seul_fichier(self):
        self.ecrire("ml/src/stockage/s3.py", "import boto3\n")
        self.ecrire("ml/src/autre.py", "import boto3\n")
        from tests import test_absence_sdk_aws as module

        module.EXCEPTIONS = frozenset({"ml/src/stockage/s3.py"})
        try:
            self.assertEqual(self.trouver(), ["ml/src/autre.py:1: importe boto3"])
        finally:
            module.EXCEPTIONS = frozenset()


if __name__ == "__main__":
    unittest.main()
