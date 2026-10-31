"""Tests des commandes dev-deps, api-run et front-dev et de leurs raccourcis make (FE-04) : rien n'est lancé pour de bon.

Lancer :  python3 -m unittest discover -s scripts/dev -p "test_dashboard_local.py" -v
"""
import argparse
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ENV = {
    "POSTGRES_DB": "novaria", "POSTGRES_PORT": "5433", "JWT_SECRET": "x" * 48,
    "PG_PASSWORD_TRAITEMENT": "p@ss/traitement", "PG_PASSWORD_APP": "p@ss/app",
}


class CommandesTests(unittest.TestCase):
    def test_les_commandes_existent(self):
        for nom in ("dev-deps", "api-run", "front-dev", "forecast-stub"):
            self.assertEqual(dev.build_parser().parse_args([nom]).command, nom)

    def test_dev_deps_installe_les_deux_fichiers_l_un_apres_l_autre(self):
        with mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(dev.cmd_dev_deps(mock.Mock()), 0)
        installes = [appel.args[0][-1] for appel in run.call_args_list]
        self.assertEqual(installes, ["services/traitement/requirements.txt", "data/etl/requirements.txt"])
        for appel in run.call_args_list:
            self.assertEqual(appel.args[0][:4], [sys.executable, "-m", "pip", "install"])

    def test_dev_deps_s_arrete_au_premier_echec(self):
        with mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=7)) as run:
            self.assertEqual(dev.cmd_dev_deps(mock.Mock()), 7)
        self.assertEqual(run.call_count, 1)


class ApiRunTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("builtins.print")  # les messages d'accueil des commandes n'ont pas à encombrer les tests
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_l_environnement_a_les_adresses_des_bases_du_poste(self):
        environnement = dev.api_environment(ENV)
        # Mot de passe encodé, hôte local, port du poste, pilote psycopg de SQLAlchemy.
        self.assertEqual(environnement["POSTGRES_URL"], "postgresql+psycopg://svc_traitement:p%40ss%2Ftraitement@127.0.0.1:5433/novaria")
        self.assertEqual(environnement["APP_DATABASE_URL"], "postgresql+psycopg://svc_app:p%40ss%2Fapp@127.0.0.1:5433/novaria")
        self.assertEqual(environnement["JWT_SECRET"], ENV["JWT_SECRET"])
        self.assertEqual(environnement["SERVICE_NAME"], "traitement")

    def test_refuse_un_secret_de_jeton_vide(self):
        with self.assertRaisesRegex(dev.DevError, "JWT_SECRET"):
            dev.api_environment({**ENV, "JWT_SECRET": ""})

    def test_lance_uvicorn_depuis_le_service_sur_le_port_du_proxy(self):
        with mock.patch.object(dev, "require_env"), mock.patch.object(dev, "etl_environment", return_value=ENV), \
                mock.patch.object(dev.importlib.util, "find_spec", return_value=object()), \
                mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(dev.cmd_api_run(mock.Mock()), 0)
        commande = run.call_args.args[0]
        self.assertEqual(commande, [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"])
        self.assertEqual(run.call_args.kwargs["cwd"], ROOT / "services" / "traitement")
        # Le port est celui que Vite vise : un test le vérifie du côté du front-end.
        self.assertIn("localhost:8000", (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8"))

    def test_n_ecrit_aucun_secret_sur_la_sortie(self):
        with mock.patch.object(dev, "require_env"), mock.patch.object(dev, "etl_environment", return_value=ENV), \
                mock.patch.object(dev.importlib.util, "find_spec", return_value=object()), \
                mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=0)), \
                mock.patch("builtins.print") as sortie:
            dev.cmd_api_run(mock.Mock())
        texte = " ".join(str(appel.args[0]) for appel in sortie.call_args_list)
        for secret in (ENV["JWT_SECRET"], "p@ss", "p%40ss"):
            self.assertNotIn(secret, texte)

    def test_dit_quoi_installer_quand_un_paquet_manque(self):
        with mock.patch.object(dev, "require_env"), mock.patch.object(dev.importlib.util, "find_spec", return_value=None):
            with self.assertRaisesRegex(dev.DevError, "dev-deps"):
                dev.cmd_api_run(mock.Mock())

    def test_ctrl_c_n_est_pas_une_erreur(self):
        with mock.patch.object(dev, "require_env"), mock.patch.object(dev, "etl_environment", return_value=ENV), \
                mock.patch.object(dev.importlib.util, "find_spec", return_value=object()), \
                mock.patch.object(dev.subprocess, "run", side_effect=KeyboardInterrupt):
            self.assertEqual(dev.cmd_api_run(mock.Mock()), 0)


class FrontDevTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("builtins.print")  # les messages d'accueil des commandes n'ont pas à encombrer les tests
        patcher.start()
        self.addCleanup(patcher.stop)

    def avec_front(self, dossier: str, *, node_modules: bool):
        racine = Path(dossier)
        if node_modules:
            (racine / "node_modules").mkdir()
        return mock.patch.object(dev, "FRONTEND_DIR", racine)

    def test_installe_les_dependances_la_premiere_fois_puis_lance_vite(self):
        with tempfile.TemporaryDirectory() as dossier, self.avec_front(dossier, node_modules=False), \
                mock.patch.object(dev.shutil, "which", return_value="/usr/bin/npm"), \
                mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(dev.cmd_front_dev(argparse.Namespace(stub=False)), 0)
        self.assertEqual([appel.args[0] for appel in run.call_args_list], [["/usr/bin/npm", "ci"], ["/usr/bin/npm", "run", "dev"]])

    def test_n_installe_rien_quand_node_modules_existe(self):
        with tempfile.TemporaryDirectory() as dossier, self.avec_front(dossier, node_modules=True), \
                mock.patch.object(dev.shutil, "which", return_value="/usr/bin/npm"), \
                mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            dev.cmd_front_dev(argparse.Namespace(stub=False))
        self.assertEqual([appel.args[0] for appel in run.call_args_list], [["/usr/bin/npm", "run", "dev"]])

    def test_s_arrete_si_l_installation_echoue(self):
        with tempfile.TemporaryDirectory() as dossier, self.avec_front(dossier, node_modules=False), \
                mock.patch.object(dev.shutil, "which", return_value="/usr/bin/npm"), \
                mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=4)) as run:
            self.assertEqual(dev.cmd_front_dev(argparse.Namespace(stub=False)), 4)
        self.assertEqual(run.call_count, 1)

    def test_avec_stub_le_proxy_de_vite_vise_la_maquette(self):
        with tempfile.TemporaryDirectory() as dossier, self.avec_front(dossier, node_modules=True), \
                mock.patch.object(dev.shutil, "which", return_value="/usr/bin/npm"), \
                mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            dev.cmd_front_dev(argparse.Namespace(stub=True))
        self.assertEqual(run.call_args.kwargs["env"]["API_TARGET"], "http://localhost:8001")

    def test_sans_stub_le_proxy_garde_l_api(self):
        with tempfile.TemporaryDirectory() as dossier, self.avec_front(dossier, node_modules=True), \
                mock.patch.dict(dev.os.environ, {}, clear=False), \
                mock.patch.object(dev.shutil, "which", return_value="/usr/bin/npm"), \
                mock.patch.object(dev.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            dev.os.environ.pop("API_TARGET", None)
            dev.cmd_front_dev(argparse.Namespace(stub=False))
        self.assertNotIn("API_TARGET", run.call_args.kwargs["env"])

    def test_le_port_de_la_maquette_est_celui_que_vise_le_front(self):
        self.assertEqual(dev.STUB_PORT, 8001)
        self.assertEqual(dev.build_parser().parse_args(["front-dev", "--stub"]).stub, True)
        self.assertEqual(dev.build_parser().parse_args(["front-dev"]).stub, False)

    def test_dit_que_npm_manque(self):
        with mock.patch.object(dev.shutil, "which", return_value=None):
            with self.assertRaisesRegex(dev.DevError, "npm"):
                dev.cmd_front_dev(argparse.Namespace(stub=False))


class ForecastStubTests(unittest.TestCase):
    def test_lance_la_maquette_devant_l_api_sur_le_port_du_proxy(self):
        import forecast_stub

        with mock.patch.object(forecast_stub, "main", return_value=0) as main:
            args = dev.build_parser().parse_args(["forecast-stub", "--back-minutes", "30"])
            self.assertEqual(dev.cmd_forecast_stub(args), 0)
        main.assert_called_once_with(["--upstream", "http://127.0.0.1:8000", "--port", "8001", "--back-minutes", "30"])

    def test_emission_decalee_d_une_heure_par_defaut(self):
        self.assertEqual(dev.build_parser().parse_args(["forecast-stub"]).back_minutes, 60)


class MakefileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    def test_les_raccourcis_appellent_la_commande_de_meme_nom(self):
        self.assertRegex(self.makefile, r"(?m)^dev-deps:.*\n\t\$\(DEV_API\) dev-deps$")
        self.assertRegex(self.makefile, r"(?m)^api-run:.*\n\t\$\(DEV_API\) api-run$")
        self.assertRegex(self.makefile, r"(?m)^front-dev:.*\n\t\$\(DEV\) front-dev$")
        self.assertRegex(self.makefile, r"(?m)^forecast-stub:.*\n\t\$\(DEV\) forecast-stub$")
        self.assertRegex(self.makefile, r"(?m)^front-dev-stub:.*\n\t\$\(DEV\) front-dev --stub$")
        self.assertRegex(self.makefile, r"(?m)^user-create:.*\n\t\$\(if \$\(U\),,.*\n\t\$\(DEV_API\) user-create \$\(U\) --role \$\(or \$\(ROLE\),viewer\)$")

    def test_les_cibles_sont_declarees_phony_et_documentees(self):
        phony = re.search(r"(?m)^\.PHONY:(.*)$", self.makefile).group(1).split()
        for cible in ("dev-deps", "user-create", "api-run", "front-dev", "forecast-stub", "front-dev-stub"):
            self.assertIn(cible, phony)
            self.assertRegex(self.makefile, rf"(?m)^{cible}:\s+##")

    def test_le_venv_du_depot_est_utilise_s_il_existe(self):
        self.assertIn("PY_API ?= $(if $(wildcard venv/bin/python),venv/bin/python,$(PY))", self.makefile)
        # Les autres cibles gardent PY : seules celles qui importent les paquets de l'API passent par le venv.
        self.assertIn("PY ?= python3", self.makefile)


if __name__ == "__main__":
    unittest.main()
