"""Contrôle de la CI multi-services (issue MS-05).

Critère d'acceptation : les 6 contrôles obligatoires gardent leur nom et couvrent tous les services ; un test en échec
dans un seul service fait échouer `backend`.

Ce test lit .github/workflows/ci.yml et **exécute** les scripts des étapes qui portent la logique, dans un dossier
temporaire : la découverte des services, le job agrégateur `backend` avec chaque combinaison de résultats, et la remise
en place des rapports de couverture pour Sonar. Il ne remplace pas un vrai run de la CI : la preuve d'un run vert et
d'un run rouge est dans l'issue MS-05.

Dépendances : PyYAML (`pip install pyyaml`), bash et jq pour les parties exécutées. Sans eux, les tests concernés sont
ignorés, pas en échec (sous Windows, les lancer depuis Git Bash).

Lancement : python3 -m unittest discover -s scripts/dev -p "test_ci.py"   (Windows : py -3 ...)
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dépend du poste
    yaml = None

RACINE = Path(__file__).resolve().parents[2]
CI = RACINE / ".github" / "workflows" / "ci.yml"
OBLIGATOIRES = {"backend", "frontend", "gitleaks", "snyk", "docker", "sonarqube"}
JOBS_D_APPUI = {"services", "service", "etl"}  # découverte, matrice et tests de data/etl : ce ne sont pas des contrôles obligatoires
BASH = shutil.which("bash")
JQ = shutil.which("jq")


def charger() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def declencheurs(doc: dict) -> dict:
    return doc.get("on", doc.get(True))  # YAML 1.1 lit la clé « on » comme le booléen vrai


def script(doc: dict, job: str, fragment: str) -> str:
    """Script `run` de l'étape du job dont le nom contient `fragment`."""
    for etape in doc["jobs"][job]["steps"]:
        if fragment in etape.get("name", "") and "run" in etape:
            return etape["run"]
    raise AssertionError(f"étape « {fragment} » introuvable dans le job {job}")


def executer(texte: str, dossier: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-e", "-c", texte], cwd=dossier, capture_output=True, text=True, encoding="utf-8",
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin", **(env or {})}, check=False)


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class LesSixControlesObligatoires(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = charger()

    def test_les_six_noms_sont_ceux_de_la_protection_de_main(self):
        self.assertLessEqual(OBLIGATOIRES, set(self.doc["jobs"]))
        self.assertEqual(set(self.doc["jobs"]) - OBLIGATOIRES, JOBS_D_APPUI)

    def test_aucun_controle_obligatoire_ne_change_son_nom_affiche(self):
        for job in OBLIGATOIRES:
            with self.subTest(job=job):
                self.assertNotIn("name", self.doc["jobs"][job])

    def test_les_jobs_d_appui_ne_portent_pas_le_nom_d_un_controle(self):
        for job in JOBS_D_APPUI:
            affiche = self.doc["jobs"][job].get("name", job)
            self.assertFalse(any(affiche.startswith(nom) for nom in OBLIGATOIRES), affiche)

    def test_aucun_filtre_de_chemin_ni_de_branche_sur_les_declencheurs(self):
        for evenement, filtres in declencheurs(self.doc).items():
            with self.subTest(evenement=evenement):
                if evenement == "pull_request":
                    self.assertIsNone(filtres, "un filtre sur pull_request laisserait des contrôles « en attente »")
                for interdit in ("paths", "paths-ignore", "branches-ignore"):
                    self.assertNotIn(interdit, filtres or {})

    def test_aucun_job_obligatoire_n_est_conditionne_a_un_chemin_ou_un_fichier(self):
        for job in OBLIGATOIRES:
            condition = str(self.doc["jobs"][job].get("if", ""))
            with self.subTest(job=job):
                self.assertNotIn("changed", condition)
                self.assertNotIn("paths", condition)
                if job in {"snyk", "docker"}:
                    self.assertEqual(condition, "", "snyk et docker tournent aussi dans le scan hebdomadaire")

    def test_aucun_controle_n_est_contourne(self):
        texte = CI.read_text(encoding="utf-8")
        for interdit in ("continue-on-error", "|| true", "--exclude-base-image-vulns", "severity-threshold=critical",
                         "severity-threshold=medium", "severity-threshold=low"):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, texte)

    def test_aucun_service_n_est_nomme_dans_la_ci(self):
        texte = CI.read_text(encoding="utf-8")
        for interdit in ("services/traitement", "services/alerte", "services/reponse", "services/collecte", "backend/"):
            self.assertNotIn(interdit, texte)


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class MatriceDesServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = charger()
        cls.service = cls.doc["jobs"]["service"]

    def test_une_execution_par_service_decouvert(self):
        self.assertEqual(self.service["needs"], "services")
        self.assertEqual(self.service["strategy"]["matrix"]["service"], "${{ fromJSON(needs.services.outputs.liste) }}")
        self.assertIs(self.service["strategy"]["fail-fast"], False)

    def test_lint_tests_et_construction_de_chaque_service(self):
        commandes = [e.get("run", "") for e in self.service["steps"]]
        for attendu in ("ruff check .", "ruff format --check .", "pytest", "pip install -r requirements-dev.txt"):
            with self.subTest(commande=attendu):
                self.assertIn(attendu, commandes)
        self.assertTrue(any(c.startswith("docker build") for c in commandes), "l'image du service n'est pas construite")
        self.assertEqual(self.service["defaults"]["run"]["working-directory"], "services/${{ matrix.service }}")

    def test_chaque_service_depose_sa_couverture_sous_son_nom(self):
        depot = next(e for e in self.service["steps"] if str(e.get("uses", "")).startswith("actions/upload-artifact"))
        self.assertEqual(depot["with"]["name"], "coverage-service-${{ matrix.service }}")
        self.assertEqual(depot["with"]["path"], "services/${{ matrix.service }}/coverage.xml")

    def test_la_matrice_ne_cite_aucun_service(self):
        self.assertNotRegex(str(self.service["strategy"]), r"(traitement|alerte|reponse|collecte|gabarit)")


@unittest.skipIf(yaml is None or BASH is None or JQ is None, "PyYAML, bash et jq sont nécessaires")
class DecouverteDesServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = script(charger(), "services", "Lister les services")

    def lancer(self, dossiers: dict[str, bool], fichiers_a_la_racine=()):
        """Crée services/<nom>/ (avec ou sans requirements-dev.txt) puis exécute le script de découverte."""
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            for nom, a_requirements in dossiers.items():
                (racine / "services" / nom).mkdir(parents=True)
                if a_requirements:
                    (racine / "services" / nom / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
            for nom in fichiers_a_la_racine:
                (racine / "services" / nom).write_text("x", encoding="utf-8")
            sortie = racine / "sortie.txt"
            sortie.write_text("", encoding="utf-8")
            resultat = executer(self.script, racine, {"GITHUB_OUTPUT": str(sortie)})
            return resultat, sortie.read_text(encoding="utf-8")

    def test_tous_les_services_sont_listes_gabarit_compris(self):
        resultat, sortie = self.lancer({"traitement": True, "alerte": True, "_gabarit": True})
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        self.assertEqual(sortie.strip(), 'liste=["_gabarit","alerte","traitement"]')

    def test_un_nouveau_service_est_decouvert_sans_modifier_la_ci(self):
        _, avant = self.lancer({"traitement": True})
        _, apres = self.lancer({"traitement": True, "reponse-exterieure": True})
        self.assertNotIn("reponse-exterieure", avant)
        self.assertIn('"reponse-exterieure"', apres)

    def test_un_dossier_sans_requirements_dev_n_est_pas_un_service(self):
        _, sortie = self.lancer({"traitement": True, "notes": False})
        self.assertEqual(sortie.strip(), 'liste=["traitement"]')

    def test_aucun_service_fait_echouer_la_decouverte(self):
        resultat, sortie = self.lancer({"notes": False})
        self.assertNotEqual(resultat.returncode, 0)
        self.assertIn("Aucun service", resultat.stdout + resultat.stderr)
        self.assertEqual(sortie, "", "rien ne doit être publié pour la matrice")

    def test_un_fichier_a_la_racine_de_services_est_ignore(self):
        _, sortie = self.lancer({"traitement": True}, fichiers_a_la_racine=("LISEZMOI",))
        self.assertEqual(sortie.strip(), 'liste=["traitement"]')


@unittest.skipIf(yaml is None or BASH is None, "PyYAML et bash sont nécessaires")
class JobAgregateurBackend(unittest.TestCase):
    """Un test en échec dans un seul service doit faire échouer `backend` ; seul le succès complet le fait réussir."""

    @classmethod
    def setUpClass(cls):
        cls.doc = charger()
        cls.job = cls.doc["jobs"]["backend"]
        cls.script = script(cls.doc, "backend", "Tous les services")

    def resultat(self, decouverte: str, services: str) -> int:
        texte = re.sub(r"\$\{\{\s*needs\.(\w+)\.result\s*\}\}",
                       lambda m: {"services": decouverte, "service": services}[m.group(1)], self.script)
        with tempfile.TemporaryDirectory() as tmp:
            return executer(texte, Path(tmp)).returncode

    def test_il_attend_la_decouverte_et_la_matrice_et_s_execute_meme_apres_un_echec(self):
        self.assertEqual(sorted(self.job["needs"]), ["service", "services"])
        self.assertIn("always()", self.job["if"])
        self.assertIn("schedule", self.job["if"])

    def test_tous_les_services_reussissent(self):
        self.assertEqual(self.resultat("success", "success"), 0)

    def test_un_seul_service_en_echec_fait_echouer_backend(self):
        # GitHub résume la matrice : « failure » dès qu'une seule exécution échoue
        self.assertNotEqual(self.resultat("success", "failure"), 0)

    def test_matrice_annulee_ou_ignoree_fait_echouer_backend(self):
        for etat in ("cancelled", "skipped"):
            with self.subTest(etat=etat):
                self.assertNotEqual(self.resultat("success", etat), 0)

    def test_decouverte_en_echec_fait_echouer_backend(self):
        for etat in ("failure", "cancelled", "skipped"):
            with self.subTest(etat=etat):
                self.assertNotEqual(self.resultat(etat, "skipped"), 0)

    def test_le_script_ne_compare_que_des_resultats_connus(self):
        self.assertEqual(set(re.findall(r"needs\.(\w+)\.result", self.script)), {"services", "service"})


@unittest.skipIf(yaml is None or BASH is None, "PyYAML et bash sont nécessaires")
class SonarRecoitLaCouvertureDeTousLesServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = charger()

    def test_sonarqube_attend_backend_frontend_et_etl(self):
        self.assertEqual(sorted(self.doc["jobs"]["sonarqube"]["needs"]), ["backend", "etl", "frontend"])

    def test_le_job_etl_mesure_la_couverture_de_data_etl_et_la_depose(self):
        job = self.doc["jobs"]["etl"]
        self.assertEqual(job["defaults"]["run"]["working-directory"], "data/etl")
        commandes = [str(e.get("run", "")) for e in job["steps"]]
        self.assertTrue(any("coverage run --source=pipelines,transforms" in c and "unittest discover -s tests" in c for c in commandes))
        self.assertTrue(any("coverage xml -o coverage.xml" in c for c in commandes))
        depot = next(e["with"] for e in job["steps"] if str(e.get("uses", "")).startswith("actions/upload-artifact"))
        self.assertEqual((depot["name"], depot["path"]), ("coverage-etl", "data/etl/coverage.xml"))

    def test_sonarqube_remet_le_rapport_de_data_etl_la_ou_sonar_le_cherche(self):
        telechargement = next(e["with"] for e in self.doc["jobs"]["sonarqube"]["steps"]
                              if str(e.get("uses", "")).startswith("actions/download-artifact") and e["with"].get("name") == "coverage-etl")
        self.assertEqual(telechargement["path"], "data/etl")
        sonar = (RACINE / "sonar-project.properties").read_text(encoding="utf-8")
        self.assertIn("sonar.python.coverage.reportPaths=services/*/coverage.xml,data/etl/coverage.xml", sonar)
        self.assertRegex(sonar, r"(?m)^sonar\.sources=.*,data,")

    def test_il_telecharge_les_rapports_de_tous_les_services(self):
        telechargements = [e["with"] for e in self.doc["jobs"]["sonarqube"]["steps"]
                           if str(e.get("uses", "")).startswith("actions/download-artifact")]
        self.assertIn("coverage-service-*", [t.get("pattern") for t in telechargements])

    def test_chaque_rapport_retrouve_son_dossier_de_service(self):
        remise = script(self.doc, "sonarqube", "Remettre la couverture")
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            for nom in ("traitement", "_gabarit", "reponse-exterieure"):
                (racine / "services" / nom).mkdir(parents=True)
                depot = racine / "coverage-services" / f"coverage-service-{nom}"
                depot.mkdir(parents=True)
                (depot / "coverage.xml").write_text(f"<coverage service='{nom}'/>", encoding="utf-8")
            resultat = executer(remise, racine)
            self.assertEqual(resultat.returncode, 0, resultat.stderr)
            for nom in ("traitement", "_gabarit", "reponse-exterieure"):
                with self.subTest(service=nom):
                    rapport = racine / "services" / nom / "coverage.xml"
                    self.assertEqual(rapport.read_text(encoding="utf-8"), f"<coverage service='{nom}'/>")

    def test_sonar_cherche_les_rapports_la_ou_la_ci_les_remet(self):
        sonar = (RACINE / "sonar-project.properties").read_text(encoding="utf-8")
        self.assertIn("sonar.python.coverage.reportPaths=services/*/coverage.xml", sonar)
        self.assertRegex(sonar, r"(?m)^sonar\.sources=.*\bservices\b")
        self.assertIn("**/tests/**", sonar)


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class SnykEtImagesParService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = charger()

    def test_une_image_par_service_est_construite_en_boucle(self):
        construction = script(self.doc, "docker", "Construire l'image de chaque service")
        self.assertIn("for dir in services/*/", construction)
        self.assertIn("docker buildx build", construction)

    def test_chaque_image_est_analysee_au_seuil_high_en_boucle(self):
        analyse = script(self.doc, "docker", "Analyse des images")
        self.assertIn("for dir in services/*/", analyse)
        self.assertIn('snyk container test "novaria-$name:${{ github.sha }}"', analyse)
        self.assertIn("--severity-threshold=high", analyse)
        self.assertIn("--policy-path=.snyk", analyse)
        self.assertIn("exit $rc", analyse)  # tous les services sont analysés, puis l'échec d'un seul fait échouer

    def test_les_dependances_de_chaque_service_sont_analysees(self):
        sca = script(self.doc, "snyk", "Dépendances Python")
        self.assertIn("for dir in services/*/", sca)
        self.assertIn("--severity-threshold=high", sca)


if __name__ == "__main__":
    unittest.main()
