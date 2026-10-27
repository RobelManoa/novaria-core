"""Contrôle du gabarit de service et de l'arborescence services/ (issue MS-04) : bibliothèque standard seulement.

Critère d'acceptation : un nouveau service créé depuis le gabarit passe lint, tests et build sans modifier la CI.
Le lint, les tests et le build eux-mêmes s'exécutent dans la CI (et à la main : voir CONTRIBUTING.md). Ce test
vérifie ce qui rend cela possible :
- le gabarit contient tout ce qu'un service doit avoir, et la commande de création le copie correctement ;
- la CI, Sonar, Dependabot, Compose et le Makefile parcourent services/*/ au lieu de nommer un service ;
- le code commun (journaux JSON, corrélation) reste identique dans tous les services.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_gabarit.py"   (Windows : py -3 ...)
"""
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import dev
import new_service

RACINE = Path(__file__).resolve().parents[2]
SERVICES = RACINE / "services"
GABARIT = SERVICES / "_gabarit"
FICHIERS_DU_GABARIT = [
    ".dockerignore", "Dockerfile", "README.md", "pyproject.toml", "requirements.txt", "requirements-dev.txt",
    "app/__init__.py", "app/main.py", "app/api/v1/health.py", "app/core/config.py", "app/core/logs.py",
    "tests/unit/test_health.py", "tests/unit/test_logs.py",
    "app/schemas/events.py", "tests/contract/conftest.py", "tests/contract/test_event_models.py",
    "tests/contract/test_openapi_contract.py",
]
# Code copié du gabarit dans chaque service (CONTRIBUTING.md : pas de bibliothèque partagée). Les modèles
# d'événements et leurs tests de conformité aux contrats de contracts/ en font partie (MS-03).
CODE_COMMUN = [
    "app/core/logs.py", "tests/unit/test_logs.py", "app/schemas/events.py",
    "tests/contract/conftest.py", "tests/contract/test_event_models.py", "tests/contract/test_openapi_contract.py",
]
JOBS_OBLIGATOIRES = {"backend", "frontend", "gitleaks", "snyk", "docker", "sonarqube"}
JOBS_D_APPUI = {"services", "service"}  # découverte des services et matrice (MS-05, voir test_ci.py)


def lire(chemin: str) -> str:
    return (RACINE / chemin).read_text(encoding="utf-8")


def services_reels() -> list[Path]:
    return sorted(p for p in SERVICES.iterdir() if p.is_dir())


class Gabarit(unittest.TestCase):
    def test_le_gabarit_contient_tout_ce_qu_un_service_doit_avoir(self):
        for fichier in FICHIERS_DU_GABARIT:
            with self.subTest(fichier=fichier):
                self.assertTrue((GABARIT / fichier).is_file())

    def test_l_image_est_en_plusieurs_etapes_et_ne_tourne_pas_en_root(self):
        dockerfile = (GABARIT / "Dockerfile").read_text(encoding="utf-8")
        self.assertGreaterEqual(len(re.findall(r"(?m)^FROM ", dockerfile)), 2)
        utilisateurs = re.findall(r"(?m)^USER (\S+)", dockerfile)
        self.assertTrue(utilisateurs)
        self.assertNotIn(utilisateurs[-1], {"root", "0"})
        self.assertRegex(dockerfile, r"(?m)^HEALTHCHECK ")
        self.assertRegex(dockerfile, r"/api/v1/health")

    def test_aucun_secret_dans_le_gabarit(self):
        for chemin in GABARIT.rglob("*"):
            if chemin.is_file() and new_service.is_text(chemin) and "__pycache__" not in chemin.parts:
                with self.subTest(fichier=chemin.relative_to(GABARIT).as_posix()):
                    self.assertNotRegex(chemin.read_text(encoding="utf-8"), r"(?i)(password|secret|token)\s*=\s*['\"][^'\"]{8,}")

    def test_le_code_commun_est_identique_dans_tous_les_services(self):
        for service in services_reels():
            if service == GABARIT:
                continue
            for fichier in CODE_COMMUN:
                with self.subTest(service=service.name, fichier=fichier):
                    attendu = new_service.substitute((GABARIT / fichier).read_text(encoding="utf-8"), service.name)
                    self.assertEqual((service / fichier).read_text(encoding="utf-8"), attendu)

    def test_chaque_service_a_les_fichiers_que_la_ci_attend(self):
        for service in services_reels():
            for fichier in ("Dockerfile", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "app/main.py"):
                with self.subTest(service=service.name, fichier=fichier):
                    self.assertTrue((service / fichier).is_file())
            self.assertTrue((service / "tests").is_dir())


class Substitution(unittest.TestCase):
    def test_le_mot_gabarit_est_remplace_mais_pas_le_dossier_modele(self):
        texte = 'service "gabarit", voir services/_gabarit et novaria-gabarit, Gabarit.'
        self.assertEqual(
            new_service.substitute(texte, "alerte"),
            'service "alerte", voir services/_gabarit et novaria-alerte, Alerte.',
        )

    def test_un_nom_a_tiret_garde_sa_majuscule_initiale(self):
        self.assertEqual(new_service.substitute("Gabarit", "reponse-exterieure"), "Reponse-exterieure")


class Creation(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        shutil.copytree(GABARIT, self.dossier / "services" / "_gabarit", ignore=new_service.SKIPPED)
        parasite = self.dossier / "services" / "_gabarit" / "app" / "__pycache__"
        parasite.mkdir()
        (parasite / "x.pyc").write_bytes(b"\x00")
        (self.dossier / "services" / "_gabarit" / "coverage.xml").write_text("<coverage/>", encoding="utf-8")

    def test_le_service_cree_porte_son_nom_partout_et_aucun_reste_du_gabarit(self):
        cible = new_service.create("reponse-exterieure", self.dossier)
        self.assertEqual(cible, self.dossier / "services" / "reponse-exterieure")
        for fichier in FICHIERS_DU_GABARIT:
            self.assertTrue((cible / fichier).is_file(), fichier)
        self.assertIn('name = "novaria-core-reponse-exterieure"', (cible / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn('service_name: str = "reponse-exterieure"', (cible / "app/core/config.py").read_text(encoding="utf-8"))
        self.assertIn("# Service reponse-exterieure", (cible / "README.md").read_text(encoding="utf-8"))
        for chemin in cible.rglob("*"):
            if chemin.is_file() and new_service.is_text(chemin):
                reste = re.findall(r"(?<![\w/])[Gg]abarit\b", chemin.read_text(encoding="utf-8"))
                self.assertEqual(reste, [], chemin.name)

    def test_les_caches_et_les_rapports_ne_sont_pas_copies(self):
        cible = new_service.create("alerte", self.dossier)
        self.assertFalse(list(cible.rglob("__pycache__")))
        self.assertFalse((cible / "coverage.xml").exists())

    def test_le_gabarit_n_est_pas_modifie(self):
        avant = {p.relative_to(self.dossier): p.read_bytes() for p in (self.dossier / "services" / "_gabarit").rglob("*") if p.is_file()}
        new_service.create("alerte", self.dossier)
        apres = {p.relative_to(self.dossier): p.read_bytes() for p in (self.dossier / "services" / "_gabarit").rglob("*") if p.is_file()}
        self.assertEqual(avant, apres)

    def test_un_nom_invalide_ou_deja_pris_est_refuse(self):
        for nom in ("", "A", "Alerte", "1alerte", "alerte_usager", "../evil", "a" * 40, "_gabarit"):
            with self.subTest(nom=nom), self.assertRaises(new_service.NewServiceError):
                new_service.create(nom, self.dossier)
        new_service.create("alerte", self.dossier)
        with self.assertRaises(new_service.NewServiceError):
            new_service.create("alerte", self.dossier)

    def test_la_commande_new_service_existe_dans_dev_py(self):
        args = dev.build_parser().parse_args(["new-service", "alerte"])
        self.assertEqual((args.command, args.name), ("new-service", "alerte"))


class ArborescenceDesFichiersDeConfiguration(unittest.TestCase):
    def test_la_ci_parcourt_les_services_sans_en_nommer_aucun(self):
        ci = lire(".github/workflows/ci.yml")
        self.assertIn("services/*/", ci)
        for interdit in ("services/traitement", "working-directory: backend", "context: backend", "backend/"):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, ci)
        jobs = set(re.findall(r"(?m)^  ([a-z]+):\n(?:    .*\n)*?    runs-on:", ci))
        self.assertEqual(jobs, JOBS_OBLIGATOIRES | JOBS_D_APPUI)

    def test_sonar_couvre_tous_les_services(self):
        sonar = lire("sonar-project.properties")
        self.assertRegex(sonar, r"(?m)^sonar\.sources=.*\bservices\b")
        self.assertIn("sonar.python.coverage.reportPaths=services/*/coverage.xml", sonar)
        self.assertIn("sonar.cpd.exclusions=services/_gabarit/**", sonar)
        self.assertNotIn("backend", sonar)

    def test_dependabot_couvre_tous_les_services(self):
        dependabot = lire(".github/dependabot.yml")
        self.assertEqual(dependabot.count('directories: ["/services/*"]'), 2)  # pip et docker
        self.assertNotIn("/backend", dependabot)

    def test_compose_construit_le_service_depuis_son_nouveau_dossier(self):
        compose = lire("docker-compose.yml")
        self.assertIn("context: ./services/traitement", compose)
        self.assertNotIn("./backend", compose)
        self.assertTrue((SERVICES / "traitement" / "Dockerfile").is_file())

    def test_le_makefile_parcourt_les_services(self):
        makefile = lire("Makefile")
        self.assertNotIn("cd backend", makefile)
        self.assertEqual(makefile.count("for d in services/*/"), 3)  # test, lint, format
        self.assertRegex(makefile, r"(?m)^new-service:")
        for ligne in makefile.splitlines():
            if re.match(r" +(@for|\$\(DEV\))", ligne):
                self.fail(f"recette indentée par des espaces au lieu d'une tabulation : {ligne!r}")

    def test_l_ancien_dossier_backend_n_est_plus_suivi_par_git(self):
        suivis = dev.subprocess.run(["git", "ls-files", "backend"], cwd=RACINE, capture_output=True, text=True)
        if suivis.returncode != 0:
            self.skipTest("git indisponible")
        self.assertEqual(suivis.stdout.strip(), "")

    def test_le_deploiement_construit_l_image_backend_depuis_le_nouveau_dossier(self):
        deploy = lire(".github/workflows/deploy.yml")
        self.assertIn("backend:services/traitement", deploy)


if __name__ == "__main__":
    unittest.main()
