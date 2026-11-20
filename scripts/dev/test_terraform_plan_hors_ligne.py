"""Plans Terraform hors ligne et protections des ressources persistantes (CLD-17), sans Docker ni réseau.

Ce qui exige Docker (le plan lui-même) se joue avec `dev.py terraform-plan-hors-ligne` ; ici on vérifie que la copie jetable est sûre
(identifiants factices, rien d'écrit dans le dépôt, AWS jamais contacté) et que **le code Terraform garde ses protections** : un test
échoue si quelqu'un retire `prevent_destroy`, le `skip_destroy` des journaux, ou invente un environnement protégé sans le dire.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_terraform_plan_hors_ligne.py"   (Windows : py -3 ...)
"""

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import terraform_plan_hors_ligne as plan

RACINE = Path(__file__).resolve().parents[2]
TERRAFORM = RACINE / "infra" / "terraform"


def lire(chemin: str) -> str:
    return (TERRAFORM / chemin).read_text(encoding="utf-8")


def bloc(texte: str, ressource: str, nom: str) -> str:
    """Le texte du bloc `resource "<ressource>" "<nom>" { ... }` (accolades équilibrées)."""
    debut = texte.index(f'resource "{ressource}" "{nom}"')
    profondeur, i = 0, texte.index("{", debut)
    for j in range(i, len(texte)):
        profondeur += {"{": 1, "}": -1}.get(texte[j], 0)
        if profondeur == 0:
            return texte[debut:j + 1]
    raise AssertionError("bloc non fermé")


class CopieJetable(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.temp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_la_copie_a_le_fournisseur_factice_et_le_depot_n_est_pas_touche(self):
        avant = {p: p.read_bytes() for p in TERRAFORM.rglob("*.tf")}
        env = plan.preparer_copie(TERRAFORM, self.temp / "terraform", "plan", "dev")
        self.assertTrue((env / plan.OVERRIDE_NOM).is_file())
        texte = (env / plan.OVERRIDE_NOM).read_text(encoding="utf-8")
        for drapeau in ("skip_credentials_validation = true", "skip_requesting_account_id  = true", "skip_metadata_api_check     = true"):
            self.assertIn(drapeau, texte)
        self.assertIn('access_key                  = "factice"', texte)
        self.assertEqual({p: p.read_bytes() for p in TERRAFORM.rglob("*.tf")}, avant)
        self.assertFalse(list(TERRAFORM.rglob(plan.OVERRIDE_NOM)), "le fournisseur factice ne doit jamais être dans le dépôt")
        self.assertFalse((env / "terraform.tfstate").exists(), "le mode plan part d'un état vide")

    def test_aucun_identifiant_ressemblant_a_un_vrai_n_est_ecrit(self):
        self.assertNotRegex(plan.OVERRIDE, r"AKIA[0-9A-Z]{16}|[A-Za-z0-9/+=]{40}")
        self.assertEqual(plan.COMPTE_FICTIF, "000000000000")

    def test_l_etat_fictif_ne_contient_qu_un_depot_protege_sur_un_compte_fictif(self):
        etat = plan.etat_fictif()
        self.assertEqual(etat["version"], 4)
        self.assertEqual([(r["type"], r["name"]) for r in etat["resources"]], [("aws_ecr_repository", "protected")])
        attributs = etat["resources"][0]["instances"][0]["attributes"]
        self.assertEqual((attributs["registry_id"], attributs["force_delete"]), ("000000000000", False))
        json.dumps(etat)  # sérialisable
        self.assertIn("fict", etat["lineage"])

    def test_le_mode_destruction_ecrit_l_etat_et_le_mode_bascule_change_la_variable_dans_la_copie_seulement(self):
        env = plan.preparer_copie(TERRAFORM, self.temp / "a", "destruction-protegee", "dev")
        self.assertTrue((env / "terraform.tfstate").is_file())
        self.assertRegex((env / "main.tf").read_text(encoding="utf-8"), r"protected\s*=\s*true")
        env2 = plan.preparer_copie(TERRAFORM, self.temp / "b", "bascule-variable", "dev")
        self.assertRegex((env2 / "main.tf").read_text(encoding="utf-8"), r"protected\s*=\s*false\s*# dépôts")
        self.assertRegex(lire("envs/dev/main.tf"), r"protected\s*=\s*true\s*# dépôts")  # le dépôt reste protégé

    def test_un_mode_inconnu_est_refuse(self):
        with self.assertRaisesRegex(ValueError, "mode inconnu"):
            plan.preparer_copie(TERRAFORM, self.temp / "c", "tout", "dev")

    def test_la_commande_docker_monte_la_copie_pas_le_depot_et_ne_transmet_aucune_variable_aws(self):
        env = plan.preparer_copie(TERRAFORM, self.temp / "d", "destruction-protegee", "dev")
        commande = plan.commande(env, "dev", "destruction-protegee")
        montages = [commande[i + 1] for i, c in enumerate(commande) if c == "-v"]
        self.assertTrue(any(m.startswith(str(self.temp / "d")) and m.endswith(":/w") for m in montages), montages)
        self.assertFalse(any(m.startswith(str(RACINE)) and not m.startswith(str(self.temp)) for m in montages), "le dépôt ne doit pas être monté")
        self.assertNotIn("AWS", " ".join(c for c in commande if c.startswith("-e") or "=" in c and c.split("=")[0].isupper()))
        script = commande[commande.index("-c") + 1] if "-c" in commande else commande[-1]
        self.assertIn("-lockfile=readonly", script)
        self.assertIn("-backend=false", script)
        self.assertIn("plan -destroy -refresh=false", script)

    def test_le_plan_simple_rafraichit_et_les_modes_a_etat_fictif_ne_rafraichissent_pas(self):
        env = plan.preparer_copie(TERRAFORM, self.temp / "e", "plan", "dev")
        self.assertNotIn("-refresh=false", plan.commande(env, "dev", "plan")[-1])
        self.assertIn("-refresh=false", plan.commande(env, "dev", "bascule-variable")[-1])

    def test_executer_rend_le_code_et_la_sortie(self):
        fait = subprocess.CompletedProcess([], 0, stdout="Plan: 15 to add, 0 to change, 0 to destroy.\n", stderr="")
        with mock.patch("subprocess.run", return_value=fait) as run:
            code, sortie = plan.executer(TERRAFORM, "plan", "dev", self.temp)
        self.assertEqual(code, 0)
        self.assertIn("15 to add", sortie)
        self.assertFalse(any(k.startswith("AWS_") for k in run.call_args.kwargs["env"]))


class Verdicts(unittest.TestCase):
    def test_chaque_mode_a_son_attendu(self):
        self.assertEqual(plan.verdict("plan", 0, "Plan: 15 to add, 0 to change, 0 to destroy."), [])
        self.assertTrue(plan.verdict("plan", 0, "Plan: 12 to add, 0 to change, 0 to destroy."))
        self.assertTrue(plan.verdict("plan", 1, "Plan: 15 to add, 0 to change, 0 to destroy."))
        refus = "Error: Instance cannot be destroyed\n lifecycle.prevent_destroy set"
        self.assertEqual(plan.verdict("destruction-protegee", 1, refus), [])
        self.assertTrue(plan.verdict("destruction-protegee", 0, "Plan: 0 to add, 0 to change, 1 to destroy."))
        self.assertEqual(plan.verdict("bascule-variable", 1, "x will be destroyed\n" + refus), [])
        self.assertTrue(plan.verdict("bascule-variable", 0, "x will be destroyed"))


class ProtectionsDuCode(unittest.TestCase):
    """Les ressources qui gardent des données (images, journaux) sont protégées dans dev et jetables dans demo : ce n'est pas un hasard."""

    def test_le_depot_protege_ne_se_detruit_pas_et_ne_purge_jamais_ses_images(self):
        protege = bloc(lire("modules/ecr/main.tf"), "aws_ecr_repository", "protected")
        self.assertRegex(protege, r"prevent_destroy\s*=\s*true")
        self.assertRegex(protege, r"force_delete\s*=\s*false")
        self.assertRegex(protege, r'image_tag_mutability\s*=\s*"IMMUTABLE"')
        self.assertRegex(protege, r"scan_on_push\s*=\s*true")

    def test_le_depot_jetable_n_a_pas_de_protection_et_suit_force_delete(self):
        jetable = bloc(lire("modules/ecr/main.tf"), "aws_ecr_repository", "disposable")
        self.assertNotIn("prevent_destroy", jetable)
        self.assertRegex(jetable, r"force_delete\s*=\s*var\.force_delete")

    def test_un_seul_des_deux_blocs_est_cree_selon_protected(self):
        texte = lire("modules/ecr/main.tf")
        self.assertRegex(texte, r"protected_services\s*=\s*var\.protected \? toset\(var\.services\) : toset\(\[\]\)")
        self.assertRegex(texte, r"disposable_services\s*=\s*var\.protected \? toset\(\[\]\) : toset\(var\.services\)")

    def test_la_valeur_par_defaut_est_la_protection(self):
        for module in ("ecr", "observability"):
            variables = lire(f"modules/{module}/variables.tf")
            self.assertRegex(bloc(variables.replace('variable "protected"', 'resource "variable" "protected"'), "variable", "protected"), r"default\s*=\s*true", module)

    def test_un_depot_protege_ne_peut_pas_avoir_force_delete(self):
        variables = lire("modules/ecr/variables.tf")
        self.assertRegex(variables, r"!\(var\.protected && var\.force_delete\)")

    def test_les_journaux_survivent_a_une_destruction_quand_protected(self):
        self.assertRegex(bloc(lire("modules/observability/main.tf"), "aws_cloudwatch_log_group", "service"), r"skip_destroy\s*=\s*var\.protected")

    def test_dev_est_protege_et_demo_jetable(self):
        dev, demo = lire("envs/dev/main.tf"), lire("envs/demo/main.tf")
        self.assertEqual(len(re.findall(r"protected\s*=\s*true", dev)), 2)
        self.assertNotRegex(dev, r"force_delete")
        self.assertEqual(len(re.findall(r"protected\s*=\s*false", demo)), 2)
        self.assertRegex(demo, r"force_delete\s*=\s*true")

    def test_aucune_autre_ressource_persistante_n_est_ajoutee_sans_protection(self):
        """Toute ressource Terraform qui garde des données doit être dans le tableau du document ; sinon ce test oblige à la décrire."""
        document = (RACINE / "docs" / "05-cloud-aws" / "ressources-persistantes.md").read_text(encoding="utf-8")
        types = set(re.findall(r'(?m)^resource "(\w+)"', "".join(p.read_text(encoding="utf-8") for p in TERRAFORM.rglob("*.tf"))))
        persistants = {"aws_ecr_repository", "aws_cloudwatch_log_group", "aws_db_instance", "aws_rds_cluster", "aws_s3_bucket", "aws_ebs_volume", "aws_efs_file_system",
                       "aws_msk_cluster", "aws_dynamodb_table", "aws_ssm_parameter", "aws_secretsmanager_secret"}
        for t in sorted(types & persistants):
            self.assertIn(t, document, f"{t} garde des données : le document des ressources persistantes doit la décrire")

    def test_le_document_cite_les_sorties_versionnees(self):
        document = (RACINE / "docs" / "05-cloud-aws" / "ressources-persistantes.md").read_text(encoding="utf-8")
        dossier = RACINE / "docs" / "05-cloud-aws" / "sorties-terraform"
        for fichier in sorted(dossier.glob("*.txt")):
            self.assertIn(fichier.name, document)
            self.assertTrue(fichier.read_text(encoding="utf-8").startswith("# "))

    def test_les_sorties_versionnees_disent_ce_qu_elles_sont(self):
        dossier = RACINE / "docs" / "05-cloud-aws" / "sorties-terraform"
        self.assertIn("Plan: 15 to add, 0 to change, 0 to destroy.", (dossier / "plan-dev-hors-ligne.txt").read_text(encoding="utf-8"))
        self.assertIn("Instance cannot be destroyed", (dossier / "destruction-protegee.txt").read_text(encoding="utf-8"))
        self.assertIn("Instance cannot be destroyed", (dossier / "bascule-variable.txt").read_text(encoding="utf-8"))
        for fichier in dossier.glob("*.txt"):
            texte = fichier.read_text(encoding="utf-8")
            self.assertRegex(texte.splitlines()[0], r"^# (Premier plan|Destruction|Même état|Terraform appliqué)")
            self.assertNotRegex(texte, r"AKIA[0-9A-Z]{16}")


if __name__ == "__main__":
    unittest.main()
