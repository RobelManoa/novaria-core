"""Contrôle des dépendances Python verrouillées des services (issue MS-06, règles SonarQube Docker S8541 et S8544).

Chaque service écrit ses dépendances en intervalles (`requirements.in`, `requirements-dev.in`) et porte un verrou
généré (`requirements.txt`, `requirements-dev.txt`) : versions exactes et empreintes SHA-256. L'image l'installe avec
`--require-hashes --only-binary :all:`. Ce test vérifie que les verrous sont complets, cohérents avec les fichiers `.in`
et réellement utilisés ; il ne remplace pas la construction de l'image (CI, job `service`).

Bibliothèque standard seulement.
Lancement : python3 -m unittest discover -s scripts/dev -p "test_dependances.py"   (Windows : py -3 ...)
"""
import argparse
import re
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
SERVICES = sorted(p for p in (RACINE / "services").iterdir() if p.is_dir())
PAQUET = re.compile(r"(?m)^([A-Za-z0-9_.-]+)==(\S+)")


def nom_normalise(nom: str) -> str:
    return re.sub(r"[-_.]+", "-", nom).lower()


def paquets_du_verrou(texte: str) -> dict[str, str]:
    return {nom_normalise(nom): version for nom, version in PAQUET.findall(texte)}


def blocs(texte: str) -> list[str]:
    """Un bloc par paquet du verrou : la ligne `nom==version` et les lignes qui la suivent."""
    return [b for b in re.split(r"(?m)^(?=[A-Za-z0-9_.-]+==)", texte) if PAQUET.match(b)]


def noms_du_fichier_in(texte: str) -> set[str]:
    noms = set()
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith(("#", "-")):
            noms.add(nom_normalise(re.split(r"[\[<>=!~; ]", ligne, maxsplit=1)[0]))
    return noms


class VerrousDesServices(unittest.TestCase):
    def test_chaque_service_a_ses_fichiers_in_et_ses_verrous(self):
        for service in SERVICES:
            for fichier in ("requirements.in", "requirements-dev.in", "requirements.txt", "requirements-dev.txt"):
                with self.subTest(service=service.name, fichier=fichier):
                    self.assertTrue((service / fichier).is_file())

    def test_chaque_paquet_du_verrou_est_epingle_avec_ses_empreintes(self):
        for service in SERVICES:
            for fichier in ("requirements.txt", "requirements-dev.txt"):
                texte = (service / fichier).read_text(encoding="utf-8")
                lignes = [b for b in blocs(texte)]
                with self.subTest(service=service.name, fichier=fichier):
                    self.assertGreater(len(lignes), 10)
                    for bloc in lignes:
                        self.assertRegex(bloc, r"--hash=sha256:[0-9a-f]{64}", bloc.splitlines()[0])

    def test_un_verrou_ne_contient_aucune_exigence_non_epinglee_ni_inclusion(self):
        for service in SERVICES:
            for fichier in ("requirements.txt", "requirements-dev.txt"):
                with self.subTest(service=service.name, fichier=fichier):
                    for ligne in (service / fichier).read_text(encoding="utf-8").splitlines():
                        if ligne and not ligne.startswith((" ", "#")) and "==" not in ligne:
                            self.fail(f"ligne non épinglée : {ligne!r}")
                        self.assertFalse(re.match(r"^\s*(-r|-c|git\+|https?://)", ligne), ligne)

    def test_les_dependances_directes_sont_dans_le_verrou(self):
        for service in SERVICES:
            for entree, verrou in (("requirements.in", "requirements.txt"), ("requirements-dev.in", "requirements-dev.txt")):
                directes = noms_du_fichier_in((service / entree).read_text(encoding="utf-8"))
                verrouillees = set(paquets_du_verrou((service / verrou).read_text(encoding="utf-8")))
                with self.subTest(service=service.name, fichier=verrou):
                    self.assertGreaterEqual(len(directes), 4)
                    self.assertEqual(directes - verrouillees, set())

    def test_les_versions_verrouillees_respectent_les_bornes_du_fichier_in(self):
        for service in SERVICES:
            verrou = paquets_du_verrou((service / "requirements.txt").read_text(encoding="utf-8"))
            for ligne in (service / "requirements.in").read_text(encoding="utf-8").splitlines():
                m = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?>=([0-9.]+),<([0-9.]+)", ligne.strip())
                if not m:
                    continue
                nom, minimum, maximum = nom_normalise(m[1]), m[2], m[3]
                version = tuple(int(x) for x in re.findall(r"\d+", verrou[nom])[:3])
                with self.subTest(service=service.name, paquet=nom):
                    self.assertGreaterEqual(version, tuple(int(x) for x in minimum.split(".")))
                    self.assertLess(version, tuple(int(x) for x in maximum.split(".")))

    def test_le_verrou_de_developpement_contient_celui_de_l_application(self):
        for service in SERVICES:
            prod = paquets_du_verrou((service / "requirements.txt").read_text(encoding="utf-8"))
            dev_ = paquets_du_verrou((service / "requirements-dev.txt").read_text(encoding="utf-8"))
            with self.subTest(service=service.name):
                self.assertEqual({n: v for n, v in prod.items() if dev_.get(n) != v}, {}, "versions différentes")
                self.assertTrue(set(prod) < set(dev_))

    def test_le_fichier_de_developpement_part_de_celui_de_l_application(self):
        for service in SERVICES:
            premiere = (service / "requirements-dev.in").read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(premiere, "-r requirements.in", service.name)

    def test_le_verrou_est_universel_il_prevoit_windows(self):
        # sans `--universal`, colorama (demandé seulement sous Windows) manquerait au poste de Daddy
        for service in SERVICES:
            texte = (service / "requirements-dev.txt").read_text(encoding="utf-8")
            with self.subTest(service=service.name):
                self.assertRegex(texte, r"(?m)^colorama==\S+ ; sys_platform == 'win32'")
                self.assertIn("--universal --generate-hashes", texte)

    def test_aucune_option_extra_qui_apporte_un_paquet_sans_roue(self):
        # uvicorn[standard] apportait pyyaml, sans roue pour Python 3.15 : l'installation binaire seule échouerait
        for service in SERVICES:
            self.assertNotIn("[standard]", (service / "requirements.in").read_text(encoding="utf-8"), service.name)
            self.assertNotIn("pyyaml", paquets_du_verrou((service / "requirements.txt").read_text(encoding="utf-8")))


class ImagesInstallantLeVerrou(unittest.TestCase):
    def test_chaque_dockerfile_exige_les_empreintes_et_les_roues(self):
        for service in SERVICES:
            texte = (service / "Dockerfile").read_text(encoding="utf-8")
            with self.subTest(service=service.name):
                self.assertIn("pip install --require-hashes --only-binary :all: --prefix=/install -r requirements.txt", texte)
                self.assertIn("COPY requirements.txt .", texte)

    def test_aucune_installation_de_paquet_sans_verrou_dans_un_dockerfile_du_depot(self):
        fichiers = [*(s / "Dockerfile" for s in SERVICES), RACINE / "simulator" / "Dockerfile", RACINE / "frontend" / "Dockerfile"]
        for fichier in fichiers:
            for ligne in fichier.read_text(encoding="utf-8").splitlines():
                if re.search(r"\bpip install\b", ligne):
                    with self.subTest(fichier=fichier.parent.name):
                        self.assertIn("--require-hashes", ligne)
                        self.assertIn("--only-binary :all:", ligne)

    def test_l_image_n_installe_pas_les_outils_de_developpement(self):
        for service in SERVICES:
            self.assertNotIn("requirements-dev", (service / "Dockerfile").read_text(encoding="utf-8"))

    def test_la_ci_installe_le_verrou_de_developpement(self):
        ci = (RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("pip install -r requirements-dev.txt", ci)


class CommandeLockDeps(unittest.TestCase):
    def test_tous_les_services_ayant_un_fichier_in_sont_concernes_gabarit_compris(self):
        self.assertEqual([d.name for d in dev.lockable_services()], [s.name for s in SERVICES])

    def test_un_service_inconnu_est_refuse(self):
        with self.assertRaises(dev.DevError):
            dev.lockable_services("inconnu")

    def test_la_commande_recalcule_les_deux_verrous_dans_un_conteneur_avec_un_outil_fixe(self):
        commande = dev.lock_command(RACINE / "services" / "alerte")
        script = commande[-1]
        self.assertEqual(commande[:3], ["docker", "run", "--rm"])
        self.assertIn(dev.LOCK_IMAGE, commande)
        self.assertIn(f"uv=={dev.UV_VERSION}", script)
        for source, cible in dev.LOCK_PAIRS:
            self.assertIn(f"uv pip compile --quiet {source} --universal --generate-hashes --python-version 3.12 -o {cible}", script)
        self.assertIn(f"{RACINE / 'services' / 'alerte'}:/work", commande)

    def test_les_fichiers_restent_a_la_personne_sous_linux_et_aucun_utilisateur_sous_windows(self):
        # `dev.os` n'est remplacé que le temps de l'appel : le vrai module `os` n'est jamais modifié
        linux = types.SimpleNamespace(getuid=lambda: 1000, getgid=lambda: 1001)
        windows = types.SimpleNamespace()  # pas de getuid sous Windows
        with mock.patch.object(dev, "os", linux):
            commande = dev.lock_command(RACINE / "services" / "alerte")
        self.assertEqual(commande[commande.index("--user") + 1], "1000:1001")
        with mock.patch.object(dev, "os", windows):
            self.assertNotIn("--user", dev.lock_command(RACINE / "services" / "alerte"))
        self.assertTrue(hasattr(dev.os, "environ"))

    def lancer(self, retour=0, service=None):
        appels = []

        def faux(commande, **kwargs):
            appels.append(commande)
            return subprocess.CompletedProcess(commande, retour)

        with mock.patch.object(dev, "require_docker"), mock.patch("subprocess.run", side_effect=faux), \
                mock.patch("builtins.print"):
            code = dev.cmd_lock_deps(argparse.Namespace(service=service))
        return code, appels

    def test_une_execution_par_service(self):
        code, appels = self.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(len(appels), len(SERVICES))

    def test_un_seul_service_si_on_le_demande(self):
        code, appels = self.lancer(service="collecte")
        self.assertEqual((code, len(appels)), (0, 1))
        self.assertIn(f"{RACINE / 'services' / 'collecte'}:/work", appels[0])

    def test_un_echec_arrete_et_remonte_le_code(self):
        code, appels = self.lancer(retour=3)
        self.assertEqual(code, 3)
        self.assertEqual(len(appels), 1, "on s'arrête au premier échec")

    def test_la_commande_existe_dans_le_lanceur_et_le_makefile(self):
        args = dev.build_parser().parse_args(["lock-deps", "alerte"])
        self.assertEqual((args.command, args.service), ("lock-deps", "alerte"))
        self.assertRegex((RACINE / "Makefile").read_text(encoding="utf-8"), r"(?m)^lock-deps:.*\n\t\$\(DEV\) lock-deps \$\(N\)$")


if __name__ == "__main__":
    unittest.main()
