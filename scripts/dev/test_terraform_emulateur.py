"""Terraform contre l'émulateur local Moto (CLD-17) : sûreté de l'exécution et exactitude du scénario, sans Docker ni réseau.

Ce qui exige Docker (apply, second plan, dérive, destroy) se joue avec `dev.py terraform-emulateur` ; ici on vérifie que
l'exécution ne peut pas atteindre le vrai AWS (réseau interne, identifiants factices, rien publié, droits retirés), que
l'image est fixée par son empreinte, que le réseau et l'émulateur sont toujours supprimés, et que chaque verdict dit vrai.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_terraform_emulateur.py"   (Windows : py -3 ...)
"""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import terraform_emulateur as te

RACINE = Path(__file__).resolve().parents[2]
TERRAFORM = RACINE / "infra" / "terraform"


def fait(code=0, sortie=""):
    return subprocess.CompletedProcess([], code, stdout=sortie, stderr="")


class Fichiers(unittest.TestCase):
    def test_l_override_redirige_ecr_et_logs_vers_l_emulateur_et_rien_d_autre(self):
        self.assertEqual(re.findall(r'(\w+)\s*=\s*"http://moto:5000"', te.OVERRIDE), ["ecr", "logs"])
        self.assertNotIn("amazonaws", te.OVERRIDE)
        self.assertIn('access_key                  = "factice"', te.OVERRIDE)
        for drapeau in ("skip_credentials_validation = true", "skip_requesting_account_id  = true", "skip_metadata_api_check     = true"):
            self.assertIn(drapeau, te.OVERRIDE)
        self.assertNotRegex(te.OVERRIDE, r"AKIA[0-9A-Z]{16}")

    def test_la_copie_a_l_override_et_le_depot_n_est_pas_touche(self):
        avant = {p: p.read_bytes() for p in TERRAFORM.rglob("*.tf")}
        with tempfile.TemporaryDirectory() as t:
            dossier = te.preparer_copie(TERRAFORM, Path(t) / "terraform", "dev")
            self.assertTrue((dossier / te.OVERRIDE_NOM).is_file())
        self.assertEqual({p: p.read_bytes() for p in TERRAFORM.rglob("*.tf")}, avant)
        self.assertFalse(list(TERRAFORM.rglob(te.OVERRIDE_NOM)))

    def test_l_image_est_fixee_par_son_empreinte(self):
        self.assertRegex(te.IMAGE_EMULATEUR, r"^motoserver/moto@sha256:[0-9a-f]{64}$")


class Surete(unittest.TestCase):
    def test_l_emulateur_tourne_sans_droits_sans_port_publie_et_sur_le_reseau_interne(self):
        c = te.commande_emulateur("reseau-x", "moto-x")
        for option in ("--read-only", "--cap-drop", "ALL", "no-new-privileges", "65534:65534"):
            self.assertIn(option, c)
        self.assertNotIn("-p", c)
        self.assertNotIn("--publish", c)
        self.assertEqual(c[c.index("--network") + 1], "reseau-x")
        self.assertEqual(c[c.index("--network-alias") + 1], "moto")

    def test_terraform_n_a_aucune_variable_aws_et_le_depot_n_est_pas_monte(self):
        c = te.commande_terraform(Path("/tmp/copie"), "dev", "terraform plan", "reseau-x")
        valeurs = [c[i + 1] for i, x in enumerate(c) if x == "-e"]
        self.assertFalse([v for v in valeurs if v.upper().startswith("AWS_")])
        self.assertIn("CHECKPOINT_DISABLE=1", valeurs)
        montages = [c[i + 1] for i, x in enumerate(c) if x == "-v"]
        self.assertIn("/tmp/copie:/w", montages)
        self.assertFalse(any(str(RACINE) in m for m in montages))
        self.assertEqual(c[c.index("--network") + 1], "reseau-x")
        self.assertNotIn("--network", te.commande_terraform(Path("/tmp/copie"), "dev", "terraform init", None))

    def test_seule_l_initialisation_quitte_le_reseau_interne(self):
        for env in ("dev", "demo"):
            for etape in te.scenario(env):
                self.assertEqual(etape.reseau_interne, not etape.nom.startswith("init"), etape.nom)

    def test_le_reseau_est_cree_interne_et_toujours_supprime(self):
        appels = []

        def run(commande, **kw):
            appels.append(commande)
            if commande[:3] == ["docker", "run", "-d"]:
                return fait(1, "pas d'image")
            return fait()

        with tempfile.TemporaryDirectory() as t, self.assertRaisesRegex(RuntimeError, "émulateur non démarré"):
            te.executer(TERRAFORM, "dev", Path(t), run=run)
        creation = next(c for c in appels if c[:3] == ["docker", "network", "create"])
        self.assertIn("--internal", creation)
        self.assertTrue(any(c[:3] == ["docker", "network", "rm"] for c in appels))
        self.assertTrue(any(c[:3] == ["docker", "rm", "-f"] for c in appels))

    def test_le_nettoyage_a_lieu_meme_si_une_etape_leve_une_exception(self):
        appels = []

        def run(commande, **kw):
            appels.append(commande)
            if "terraform" in " ".join(commande) and "init" in " ".join(commande):
                raise OSError("docker a disparu")
            return fait()

        with tempfile.TemporaryDirectory() as t, self.assertRaises(OSError):
            te.executer(TERRAFORM, "dev", Path(t), run=run, attendre_emulateur=lambda n: None)
        self.assertTrue(any(c[:3] == ["docker", "network", "rm"] for c in appels))


class Scenario(unittest.TestCase):
    def test_le_second_plan_exige_zero_changement_et_le_code_zero(self):
        etape = next(e for e in te.scenario("dev") if e.nom.startswith("SECOND PLAN :"))
        self.assertEqual(etape.verifier(0, "No changes. Your infrastructure matches the configuration."), [])
        self.assertTrue(etape.verifier(0, "Plan: 0 to add, 1 to change, 0 to destroy."))
        self.assertTrue(etape.verifier(2, "No changes. Your infrastructure matches the configuration."))

    def test_la_derive_doit_etre_vue_sinon_le_controle_ne_vaut_rien(self):
        etape = next(e for e in te.scenario("dev") if e.nom.startswith("plan après la dérive"))
        self.assertEqual(etape.verifier(2, "Plan: 0 to add, 1 to change, 0 to destroy."), [])
        self.assertTrue(etape.verifier(0, "No changes. Your infrastructure matches the configuration."))

    def test_dev_refuse_la_destruction_et_garde_les_journaux_demo_detruit_tout(self):
        dev = [e.nom for e in te.scenario("dev")]
        demo = [e.nom for e in te.scenario("demo")]
        self.assertIn("destroy complet : refusé (dépôts protégés, sur un vrai état)", dev)
        self.assertTrue(any("skip_destroy" in n for n in dev))
        self.assertTrue(any("destroy complet : réussit" in n for n in demo))
        refus = next(e for e in te.scenario("dev") if "refusé" in e.nom)
        self.assertEqual(refus.verifier(1, "Error: Instance cannot be destroyed\n lifecycle.prevent_destroy set"), [])
        self.assertTrue(refus.verifier(0, "Destroy complete! Resources: 15 destroyed."))

    def test_les_journaux_proteges_restent_visibles_dans_l_emulateur(self):
        etape = next(e for e in te.scenario("dev") if e.nom.startswith("les journaux existent"))
        cinq = '{"logGroups": [' + ",".join('{"logGroupName": "/novaria/dev/%d"}' % i for i in range(5)) + "]}"
        self.assertEqual(etape.verifier(0, cinq), [])
        self.assertTrue(etape.verifier(0, '{"logGroups": []}'))

    def test_les_appels_a_l_api_des_journaux_visent_l_emulateur_et_le_bon_groupe(self):
        derive = next(e for e in te.scenario("dev") if e.nom.startswith("dérive"))
        self.assertIn("http://moto:5000/", derive.script)
        self.assertIn("Logs_20140328.PutRetentionPolicy", derive.script)
        self.assertIn("/novaria/dev/alerte", derive.script)
        self.assertIn("/novaria/demo/alerte", next(e for e in te.scenario("demo") if e.nom.startswith("dérive")).script)

    def test_le_nombre_de_ressources_est_celui_du_code(self):
        total = 0
        for chemin in ("modules/ecr/main.tf", "modules/observability/main.tf"):
            total += len(re.findall(r'(?m)^resource "', (TERRAFORM / chemin).read_text(encoding="utf-8")))
        # ecr : deux blocs de dépôt (un seul créé) + une politique ; journaux : un bloc : 3 ressources créées par service
        self.assertEqual(total, 4)
        self.assertEqual(te.RESSOURCES, 3 * te.SERVICES)
        defaut = re.search(r'default\s*=\s*\[(.*?)\]', (TERRAFORM / "envs/dev/variables.tf").read_text(encoding="utf-8"), re.S).group(1)
        self.assertEqual(len(re.findall(r'"\w+"', defaut)), te.SERVICES)


class Execution(unittest.TestCase):
    def _executer(self, sorties):
        """Joue le scénario `demo` avec des sorties simulées par nom d'étape ; les appels Terraform se suivent dans l'ordre du scénario."""
        etapes = iter(te.scenario("demo"))

        def run(commande, **kw):
            if commande[:3] == ["docker", "run", "--rm"]:  # un conteneur Terraform : l'étape suivante du scénario
                return sorties.get(next(etapes).nom, fait())
            return fait()

        with tempfile.TemporaryDirectory() as t:
            return te.executer(TERRAFORM, "demo", Path(t), run=run, attendre_emulateur=lambda n: None)

    def test_un_scenario_conforme_ne_donne_aucun_ecart(self):
        sorties = {}
        for e in te.scenario("demo"):
            if e.nom.startswith("init"):
                sorties[e.nom] = fait(0, "Terraform has been successfully initialized!")
            elif e.nom.startswith("apply :"):
                sorties[e.nom] = fait(0, "Apply complete! Resources: 15 added, 0 changed, 0 destroyed.")
            elif e.nom.startswith("SECOND PLAN"):
                sorties[e.nom] = fait(0, "No changes. Your infrastructure matches the configuration.")
            elif e.nom.startswith("plan après"):
                sorties[e.nom] = fait(2, "Plan: 0 to add, 1 to change, 0 to destroy.")
            elif e.nom.startswith("apply de"):
                sorties[e.nom] = fait(0, "Apply complete! Resources: 0 added, 1 changed, 0 destroyed.")
            elif e.nom.startswith("destroy"):
                sorties[e.nom] = fait(0, "Destroy complete! Resources: 15 destroyed.")
            elif e.nom.startswith("les journaux"):
                sorties[e.nom] = fait(0, '{"logGroups": []}')
        resultats = self._executer(sorties)
        self.assertEqual(te.verdict(resultats), [])
        self.assertEqual(len(resultats), len(te.scenario("demo")))

    def test_un_second_plan_qui_voit_un_changement_est_un_ecart_nomme(self):
        sorties = {e.nom: fait(0, "Terraform has been successfully initialized!") for e in te.scenario("demo") if e.nom.startswith("init")}
        sorties.update({e.nom: fait(0, "Apply complete! Resources: 15 added, 0 changed, 0 destroyed.") for e in te.scenario("demo") if e.nom.startswith("apply :")})
        sorties.update({e.nom: fait(2, "Plan: 0 to add, 1 to change, 0 to destroy.") for e in te.scenario("demo") if e.nom.startswith("SECOND PLAN :")})
        resultats = self._executer(sorties)
        ecarts = te.verdict(resultats)
        self.assertTrue(any(e.startswith("SECOND PLAN : doit indiquer 0 changement") for e in ecarts), ecarts)

    def test_une_initialisation_en_echec_arrete_tout(self):
        resultats = self._executer({e.nom: fait(1, "Error: Failed to query available provider packages") for e in te.scenario("demo") if e.nom.startswith("init")})
        self.assertEqual(len(resultats), 1)
        self.assertFalse(resultats[0].ok)

    def test_la_transcription_dit_ce_qu_elle_est_et_garde_chaque_sortie(self):
        etape = te.scenario("dev")[2]
        texte = te.transcription([te.Resultat(etape, 0, "No changes.", [])], "dev", "2026-11-19")
        self.assertIn("ÉMULATEUR", texte)
        self.assertIn("2026-11-19", texte)
        self.assertIn("Étape 1 : SECOND PLAN", texte)
        self.assertIn("conforme", texte)
        self.assertIn("No changes.", texte)
        self.assertIn("ÉCART : x", te.transcription([te.Resultat(etape, 1, "", ["x"])], "dev"))


class CommandeDev(unittest.TestCase):
    def test_la_commande_ecrit_le_compte_rendu_et_donne_le_code_du_verdict(self):
        import dev

        etape = te.scenario("demo")[0]
        with tempfile.TemporaryDirectory() as t, mock.patch.object(dev, "require_docker"), \
                mock.patch.object(te, "executer", return_value=[te.Resultat(etape, 0, "sortie", [])]), mock.patch("builtins.print"):
            cible = Path(t) / "sous" / "compte-rendu.txt"
            self.assertEqual(dev.main(["terraform-emulateur", "--env", "demo", "--sortie", str(cible)]), 0)
            self.assertIn("sortie", cible.read_text(encoding="utf-8"))
            self.assertEqual(cible.read_text(encoding="utf-8").splitlines()[0][:2], "# ")
        with mock.patch.object(dev, "require_docker"), mock.patch.object(te, "executer", return_value=[te.Resultat(etape, 1, "", ["écart"])]), \
                mock.patch("builtins.print"), mock.patch("sys.stderr"):
            self.assertEqual(dev.main(["terraform-emulateur"]), 1)
        with mock.patch.object(dev, "require_docker"), mock.patch.object(te, "executer", return_value=[]), mock.patch("builtins.print"):
            self.assertEqual(dev.main(["terraform-emulateur"]), 1)  # aucune étape jouée : jamais « réussi »


if __name__ == "__main__":
    unittest.main()
