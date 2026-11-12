"""Le flux de travail `mlsecops.yml` (IA-05) : manuel, sans paramètre, sans secret, avec une porte qui bloque l'enregistrement.

Ce test lit le fichier et fixe ce qui rend le pipeline sûr : un déclencheur sans entrée (personne ne règle le seuil au
lancement), des droits en lecture seule, aucune interpolation dans les scripts (injection), des dépendances à empreintes,
aucun contournement (`continue-on-error`), et l'ordre des étapes (la porte précède l'enregistrement).
Lancement : python3 -m unittest discover -s scripts/dev -p "test_mlsecops.py"   (Windows : py -3 ...)
"""
import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dépend du poste
    yaml = None

RACINE = Path(__file__).resolve().parents[2]
FICHIER = RACINE / ".github" / "workflows" / "mlsecops.yml"
VERROUS = ("ml/requirements.txt", "ml/requirements-mlsecops.txt", "ml/requirements-dev.txt")


def charger() -> dict:
    document = yaml.safe_load(FICHIER.read_text(encoding="utf-8"))
    document["on"] = document.get("on", document.get(True))  # YAML 1.1 lit « on » comme le booléen vrai
    return document


@unittest.skipIf(yaml is None, "PyYAML absent : pip install pyyaml")
class FluxDeTravailMlsecops(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brut = FICHIER.read_text(encoding="utf-8")
        cls.texte = "\n".join(ligne for ligne in cls.brut.splitlines() if not ligne.lstrip().startswith("#"))  # sans les commentaires
        cls.doc = charger()
        cls.pas = cls.doc["jobs"]["pipeline"]["steps"]

    def noms(self):
        return [p.get("name", "") for p in self.pas]

    def indice(self, debut: str) -> int:
        return next(i for i, nom in enumerate(self.noms()) if nom.startswith(debut))

    def test_declenche_a_la_main_seulement_et_sans_aucun_parametre(self):
        self.assertEqual(self.doc["on"], {"workflow_dispatch": None}, "ni push, ni pull_request, ni planification, ni entrée")
        self.assertNotIn("inputs", self.texte.split("jobs:")[0], "aucune entrée : personne ne règle le seuil au lancement")
        self.assertNotIn("github.event.inputs", self.texte)
        self.assertNotIn("inputs.", self.texte)

    def test_droits_en_lecture_seule_et_aucun_jeton_d_identite(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        for job in self.doc["jobs"].values():
            self.assertNotIn("permissions", job, "un job n'élargit pas les droits")
        self.assertNotIn("id-token", self.texte)

    def test_aucun_secret_aucun_compte_aws_aucun_contournement(self):
        self.assertNotRegex(self.texte, r"secrets\.")
        self.assertNotRegex(self.texte, r"(?i)\baws\b|aws-actions|sagemaker|AWS_ROLE_ARN")
        self.assertNotIn("continue-on-error", self.texte)
        self.assertNotIn("--no-verify", self.texte)

    def test_aucune_interpolation_dans_les_scripts(self):
        """Une expression `${{ ... }}` dans un `run:` est une injection possible ; les valeurs passent par `env:`."""
        for pas in self.pas:
            with self.subTest(pas=pas.get("name")):
                self.assertNotIn("${{", pas.get("run", ""))

    def test_toute_installation_exige_les_empreintes(self):
        installations = [ligne for pas in self.pas for ligne in str(pas.get("run", "")).splitlines() if re.search(r'pip"? install', ligne)]
        self.assertEqual(len(installations), 2)
        for ligne in installations:
            self.assertIn("--require-hashes", ligne)
            self.assertRegex(ligne, r"-r ml/requirements(-mlsecops)?\.txt")

    def test_les_verrous_portent_une_empreinte_par_paquet(self):
        for nom in VERROUS:
            texte = (RACINE / nom).read_text(encoding="utf-8")
            paquets = [ligne for ligne in texte.splitlines() if ligne and ligne[0].isalpha()]
            self.assertTrue(paquets, nom)
            for paquet in paquets:
                bloc = texte.split(paquet, 1)[1].split("\n\n", 1)[0]
                with self.subTest(verrou=nom, paquet=paquet.split()[0]):
                    self.assertIn("--hash=sha256:", bloc)

    def test_checkout_sans_jeton_persistant_delai_et_concurrence(self):
        checkout = next(p for p in self.pas if str(p.get("uses", "")).startswith("actions/checkout"))
        self.assertIs(checkout["with"]["persist-credentials"], False)
        self.assertIn("timeout-minutes", self.doc["jobs"]["pipeline"])
        self.assertIs(self.doc["concurrency"]["cancel-in-progress"], False)

    def test_la_porte_precede_l_enregistrement_et_l_enregistrement_ne_tourne_pas_apres_un_echec(self):
        evaluer, porte, enregistrer = self.indice("Entraîner et évaluer"), self.indice("Porte"), self.indice("Enregistrer le modèle")
        self.assertLess(evaluer, porte)
        self.assertLess(porte, enregistrer)
        self.assertIn("executer_pipeline.py porte", self.pas[porte]["run"])
        self.assertIn("executer_pipeline.py enregistrer", self.pas[enregistrer]["run"])
        self.assertNotIn("if", self.pas[porte], "la porte ne se saute jamais")
        self.assertNotIn("if", self.pas[enregistrer], "après un échec de la porte, l'étape suivante est sautée (condition par défaut : success())")

    def test_le_resume_et_le_rapport_sont_conserves_meme_apres_un_echec(self):
        resume = self.pas[self.indice("Résumé")]
        rapport = self.pas[self.indice("Conserver le rapport")]
        self.assertEqual((resume["if"], rapport["if"]), ("always()", "always()"))
        self.assertEqual(rapport["with"]["path"], "var/pipeline/")

    def test_le_pipeline_n_ecrit_pas_dans_le_depot(self):
        """Le jeu est reconstruit puis comparé à sa fiche versionnée ; aucune étape ne commite ni ne pousse."""
        reconstruction = self.pas[self.indice("Reconstruire le jeu")]["run"]
        self.assertIn("construire_jeu.py", reconstruction)
        self.assertIn("git diff --exit-code -- data/datasets", reconstruction)
        for mot in ("git push", "git commit", "git add"):
            self.assertNotIn(mot, self.texte)

    def test_l_audit_a_son_environnement_a_part_et_son_chemin_passe_par_env(self):
        evaluation = self.pas[self.indice("Entraîner et évaluer")]
        self.assertIn("PIP_AUDIT", evaluation["env"])
        self.assertIn("runner.temp", evaluation["env"]["PIP_AUDIT"])
        self.assertIn("-m venv", self.pas[self.indice("Outil d'audit")]["run"])

    def test_les_actions_sont_celles_du_depot_a_la_meme_version(self):
        ci = (RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        versions_ci = dict(re.findall(r"uses: (actions/[\w-]+)@(v\d+)", ci))
        for pas in self.pas:
            usage = str(pas.get("uses", ""))
            if usage:
                action, version = usage.split("@")
                self.assertIn(action, versions_ci, f"{action} n'est pas utilisée par ci.yml")
                self.assertEqual(version, versions_ci[action])

    def test_le_flux_de_travail_n_est_pas_un_controle_obligatoire_de_main(self):
        ci = (RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("mlsecops", ci)
        self.assertEqual(self.doc["name"], "MLSecOps")


if __name__ == "__main__":
    unittest.main()
