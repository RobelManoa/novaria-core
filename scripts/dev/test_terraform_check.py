"""Contrôles Terraform sans compte (issue LOC-06) : le squelette de infra/terraform et le script qui le contrôle.

Ces tests ne lancent ni Docker ni Terraform (voir `dev.py terraform-check` pour les contrôles eux-mêmes). Ils vérifient que :
- les commandes sont identiques sous Linux et sous Windows, à versions fixées, sans variable AWS et avec le dépôt en lecture seule ;
- un contrôle non lancé (jeton Snyk absent) n'est jamais présenté comme réussi ;
- le squelette garde ses invariants : fournisseurs et Terraform épinglés, verrou versionné, aucun secret ni état.

Bibliothèque standard seulement.
Lancement : python3 -m unittest discover -s scripts/dev -p "test_terraform_check.py"   (Windows : py -3 ...)
"""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import terraform_check as tc  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
TERRAFORM = RACINE / "infra" / "terraform"


def fausse_execution(codes=None):
    """Remplace subprocess.run : renvoie le code prévu pour la commande (0 sinon) et note les appels."""
    appels = []

    def faux(commande, **kwargs):
        appels.append(commande)
        code = (codes or {}).get(" ".join(commande), 0)
        return subprocess.CompletedProcess(commande, code, stdout="sortie", stderr="")

    faux.appels = appels
    return faux


class Commandes(unittest.TestCase):
    def setUp(self):
        self.etapes = tc.build_steps(TERRAFORM)

    def test_les_controles_de_l_issue_sont_tous_la_dans_l_ordre(self):
        noms = [e.name for e in self.etapes]
        self.assertEqual(noms[0], "terraform fmt")
        for env in tc.environments(TERRAFORM):
            self.assertLess(noms.index(f"terraform init ({env})"), noms.index(f"terraform validate ({env})"))
        self.assertLess(noms.index("terraform validate (dev)"), noms.index("tflint"))
        self.assertEqual(noms[-1], "snyk iac")

    def test_fmt_verifie_sans_rien_ecrire(self):
        commande = self.etapes[0].command
        self.assertEqual(commande[-5:], ["fmt", "-check", "-recursive", "-diff", "-no-color"])
        self.assertIn(f"{TERRAFORM}:/w:ro", commande)

    def test_init_ne_touche_pas_a_l_etat_distant_et_respecte_le_verrou(self):
        init = next(e for e in self.etapes if e.name == "terraform init (dev)")
        script = init.command[init.command.index("-c") + 1]
        self.assertIn("-backend=false", script)
        self.assertIn("-lockfile=readonly", script)
        self.assertIn("/w/envs/dev", init.command)

    def test_le_cache_des_fournisseurs_n_est_declare_que_la_ou_il_est_cree(self):
        for etape in self.etapes:
            declare = "TF_PLUGIN_CACHE_DIR=/cache/plugins" in etape.command
            self.assertEqual(declare, etape.name.startswith("terraform init"), etape.name)

    def test_le_depot_est_toujours_monte_en_lecture_seule(self):
        for etape in self.etapes:
            montages = [a for a in etape.command if a.startswith(str(TERRAFORM))]
            self.assertTrue(montages, etape.name)
            for montage in montages:
                self.assertTrue(montage.endswith(":ro"), f"{etape.name} : {montage}")

    def test_versions_fixees_et_aucune_etiquette_latest(self):
        for image in (tc.TERRAFORM_IMAGE, tc.TFLINT_IMAGE, tc.SNYK_IMAGE):
            self.assertNotIn(":latest", image)
            self.assertNotRegex(image, r"^[^:@]+$")  # une étiquette ou un résumé est obligatoire
        for etape in self.etapes:
            self.assertTrue(any(a in (tc.TERRAFORM_IMAGE, tc.TFLINT_IMAGE, tc.SNYK_IMAGE) for a in etape.command), etape.name)

    def test_aucune_variable_aws_n_est_transmise_et_le_jeton_snyk_n_est_jamais_ecrit_dans_la_commande(self):
        for etape in self.etapes:
            self.assertFalse([a for a in etape.command if "AWS" in a.upper()], etape.name)
        snyk = self.etapes[-1].command
        self.assertEqual(snyk[snyk.index("-e") + 1], "SNYK_TOKEN")  # le nom seul : la valeur reste dans l'environnement

    def test_l_environnement_du_processus_retire_toute_variable_aws(self):
        base = {"PATH": "/usr/bin", "AWS_ACCESS_KEY_ID": "x", "aws_profile": "y", "AWS_REGION": "eu-west-1"}
        env = tc.process_environment("jeton", base)
        self.assertEqual(env, {"PATH": "/usr/bin", "SNYK_TOKEN": "jeton"})
        self.assertNotIn("SNYK_TOKEN", tc.process_environment(None, base))

    def test_pas_de_chemin_propre_a_un_systeme(self):
        # le dépôt est monté tel quel (Windows : C:\...) ; tout le reste utilise des barres obliques dans le conteneur
        for etape in self.etapes:
            for argument in etape.command:
                if argument != str(TERRAFORM) and not argument.startswith(str(TERRAFORM)):
                    self.assertNotIn("\\", argument, etape.name)

    def test_un_dossier_sans_environnement_est_refuse(self):
        with tempfile.TemporaryDirectory() as vide:
            with self.assertRaises(tc.TerraformCheckError):
                tc.build_steps(Path(vide))

    def test_le_verrou_est_ecrit_au_nom_de_la_personne_pour_chaque_plateforme_declaree(self):
        etapes = tc.lock_steps(TERRAFORM, "1000:1001")
        self.assertEqual([e.name for e in etapes], ["verrou des fournisseurs (demo)", "verrou des fournisseurs (dev)"])
        commande = etapes[0].command
        self.assertEqual(commande[commande.index("--user") + 1], "1000:1001")
        script = commande[commande.index("-c") + 1]
        for plateforme in tc.LOCK_PLATFORMS:
            self.assertIn(f"-platform={plateforme}", script)
        self.assertNotIn("--user", tc.lock_steps(TERRAFORM, None)[0].command)


class Execution(unittest.TestCase):
    def lancer(self, etapes, run):
        sorties = []
        resultats = tc.run_steps(etapes, run=run, echo=sorties.append)
        return resultats, "\n".join(sorties)

    def test_tout_reussit_code_zero(self):
        run = fausse_execution()
        resultats, _ = self.lancer(tc.build_steps(TERRAFORM), run)
        self.assertEqual({r.status for r in resultats}, {tc.OK})
        self.assertEqual(tc.exit_code(resultats), 0)
        self.assertEqual(len(run.appels), len(resultats))

    def test_un_echec_n_arrete_pas_les_autres_controles_et_montre_sa_sortie(self):
        etapes = tc.build_steps(TERRAFORM)
        en_echec = next(e for e in etapes if e.name == "terraform validate (demo)")
        resultats, texte = self.lancer(etapes, fausse_execution({" ".join(en_echec.command): 1}))
        self.assertEqual(tc.exit_code(resultats), 1)
        self.assertEqual([r.step.name for r in resultats if r.status == tc.KO], ["terraform validate (demo)"])
        self.assertEqual(len(resultats), len(etapes))
        self.assertIn("sortie", texte)

    def test_sans_jeton_snyk_le_controle_est_incomplet_et_non_reussi(self):
        etapes = tc.build_steps(TERRAFORM, snyk_token=False)
        run = fausse_execution()
        resultats, texte = self.lancer(etapes, run)
        self.assertEqual(resultats[-1].status, tc.SKIPPED)
        self.assertEqual(tc.exit_code(resultats), 2)
        self.assertEqual(len(run.appels), len(etapes) - 1)  # Snyk n'a pas été appelé
        self.assertIn("SNYK_TOKEN", texte)

    def test_ecarter_snyk_explicitement_retire_l_etape(self):
        noms = [e.name for e in tc.build_steps(TERRAFORM, snyk_token=False, with_snyk=False)]
        self.assertNotIn("snyk iac", noms)

    def test_un_echec_passe_avant_un_saut(self):
        etapes = tc.build_steps(TERRAFORM, snyk_token=False)
        run = fausse_execution({" ".join(etapes[0].command): 1})
        resultats, _ = self.lancer(etapes, run)
        self.assertEqual(tc.exit_code(resultats), 1)

    def test_docker_absent_est_signale_clairement(self):
        def absent(commande, **kwargs):
            raise FileNotFoundError("docker")

        with self.assertRaises(tc.TerraformCheckError):
            tc.run_steps(tc.build_steps(TERRAFORM), run=absent, echo=lambda _: None)


class Squelette(unittest.TestCase):
    """Invariants de infra/terraform (ADR-020 §4.1) ; ils échouent si un fichier .tf s'en écarte."""

    def fichiers(self, motif):
        return sorted(TERRAFORM.rglob(motif))

    def test_les_environnements_ont_du_code_et_le_depot_n_est_plus_vide(self):
        self.assertEqual(tc.environments(TERRAFORM), ["demo", "dev"])
        self.assertTrue(self.fichiers("modules/*/main.tf"))

    def test_chaque_environnement_et_chaque_module_epingle_terraform_et_le_fournisseur(self):
        dossiers = [p for p in TERRAFORM.glob("envs/*") if p.is_dir()] + [p for p in TERRAFORM.glob("modules/*") if p.is_dir()]
        self.assertEqual(len(dossiers), 4)
        for dossier in dossiers:
            texte = (dossier / "versions.tf").read_text(encoding="utf-8")
            self.assertRegex(texte, r'required_version\s*=\s*">=\s*\d+\.\d+\.\d+,\s*<\s*\d+\.\d+\.\d+"', dossier.name)
            self.assertRegex(texte, r'version\s*=\s*"~>\s*\d+\.\d+"', dossier.name)

    def test_chaque_environnement_versionne_son_verrou_avec_une_empreinte_par_plateforme_declaree(self):
        for env in tc.environments(TERRAFORM):
            verrou = TERRAFORM / "envs" / env / ".terraform.lock.hcl"
            self.assertTrue(verrou.is_file(), f"{verrou} manquant : make terraform-check LOCK=1")
            texte = verrou.read_text(encoding="utf-8")
            self.assertIn('provider "registry.terraform.io/hashicorp/aws"', texte)
            self.assertGreaterEqual(len(re.findall(r'"h1:', texte)), len(tc.LOCK_PLATFORMS), env)

    def test_aucun_secret_etat_ou_valeur_de_variables_dans_le_squelette(self):
        for interdit in ("*.tfstate", "*.tfstate.*", "*.tfvars"):
            self.assertEqual(self.fichiers(interdit), [], interdit)
        motifs = [r"AKIA[0-9A-Z]{16}", r"(?i)secret_key\s*=", r"(?i)access_key\s*=", r"(?i)password\s*=", r"\b\d{12}\b"]
        for fichier in self.fichiers("*.tf"):
            texte = fichier.read_text(encoding="utf-8")
            for motif in motifs:
                self.assertIsNone(re.search(motif, texte), f"{fichier.name} : {motif}")

    def test_les_etiquettes_communes_sont_appliquees_par_defaut_au_fournisseur(self):
        for env in tc.environments(TERRAFORM):
            texte = (TERRAFORM / "envs" / env / "main.tf").read_text(encoding="utf-8")
            self.assertIn("default_tags", texte)
            for etiquette in ("projet", "env", "proprietaire"):
                self.assertRegex(texte, rf"\b{etiquette}\s*=", f"{env} : {etiquette}")

    def test_la_region_par_defaut_est_celle_de_l_adr_006_et_aucun_etat_distant_n_est_declare(self):
        for env in tc.environments(TERRAFORM):
            variables = (TERRAFORM / "envs" / env / "variables.tf").read_text(encoding="utf-8")
            self.assertIn('default     = "eu-west-1"', variables)
            self.assertNotIn('backend "s3"', (TERRAFORM / "envs" / env / "main.tf").read_text(encoding="utf-8"))

    def test_la_configuration_de_tflint_existe_et_epingle_son_plugin(self):
        texte = (TERRAFORM / ".tflint.hcl").read_text(encoding="utf-8")
        self.assertRegex(texte, r'version\s*=\s*"\d+\.\d+\.\d+"')


if __name__ == "__main__":
    unittest.main()
