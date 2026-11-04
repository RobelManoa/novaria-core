"""Aucun secret en clair dans le dépôt ni dans les variables (BE-08) : contrôle des fichiers de configuration.

Complète gitleaks (qui cherche des motifs dans l'historique) par des règles du projet, lisibles et
sans faux positif :
- `.env` n'est jamais suivi par Git ; seul `.env.example` l'est, et il ne contient que la valeur
  d'exemple `change-me-local` pour chaque secret ;
- `dev.py init-env` remplace chaque valeur d'exemple par un secret aléatoire, long, différent à
  chaque exécution, sans en laisser aucune ;
- dans docker-compose.yml, les Dockerfile, les workflows et les définitions de tâches ECS, toute
  variable dont le nom dit « secret » (mot de passe, jeton, clé...) est une **référence**
  (`${NOM}`, `secrets.NOM`, `valueFrom`), jamais une valeur écrite ;
- aucune adresse de connexion n'y porte un mot de passe écrit.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_secrets_environnement.py"
(Windows : py -3 ...)
"""

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
NOM_SECRET = re.compile(r"PASSWORD|SECRET|TOKEN|_KEY\b|CREDENTIAL", re.IGNORECASE)
REFERENCE = re.compile(r"^\s*[\"']?(\$\{[^}]*\}|\$\{\{\s*secrets\.[A-Z0-9_]+\s*\}\}|)[\"']?\s*(#.*)?$")
URL_AVEC_MOT_DE_PASSE = re.compile(r"://[^/\s:@\"']+:([^@\s\"']+)@")


def fichiers_suivis(*motifs: str) -> list[Path]:
    sortie = subprocess.run(["git", "ls-files"], cwd=RACINE, capture_output=True, text=True, check=True).stdout
    return [RACINE / f for f in sortie.splitlines() if any(re.search(m, f) for m in motifs)]


def affectations(texte: str):
    """(nom, valeur) de chaque `NOM: valeur` ou `NOM=valeur` d'un YAML, d'un Dockerfile ou d'un .env."""
    for ligne in texte.splitlines():
        if ligne.lstrip().startswith("#"):
            continue
        trouve = re.match(r"^\s*(?:-\s*)?(?:ENV\s+|ARG\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.*)$", ligne)
        if trouve:
            yield trouve.group(1), trouve.group(2)


@unittest.skipIf(shutil.which("git") is None, "git est nécessaire")
class DepotSansSecret(unittest.TestCase):
    def test_seul_env_example_est_suivi_par_git(self):
        suivis = [p.name for p in fichiers_suivis(r"(^|/)\.env")]
        self.assertEqual(suivis, [".env.example"])

    def test_env_et_ses_variantes_sont_ignores(self):
        for nom in (".env", ".env.local", ".env.production", ".env.bak", "services/traitement/.env"):
            with self.subTest(fichier=nom):
                resultat = subprocess.run(["git", "check-ignore", "-q", nom], cwd=RACINE)
                self.assertEqual(resultat.returncode, 0, f"{nom} doit être ignoré par .gitignore")
        resultat = subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=RACINE)
        self.assertEqual(resultat.returncode, 1, ".env.example doit rester suivi")

    def test_les_cles_et_certificats_ne_sont_pas_suivis(self):
        self.assertEqual(fichiers_suivis(r"\.(pem|key|p12|pfx|tfstate)$", r"\.tfvars$"), [])


class EnvExample(unittest.TestCase):
    def setUp(self):
        self.texte = (RACINE / ".env.example").read_text(encoding="utf-8")
        self.variables = dict(affectations(self.texte))

    def test_chaque_secret_porte_la_valeur_d_exemple_et_rien_d_autre(self):
        secrets = {nom: valeur for nom, valeur in self.variables.items() if NOM_SECRET.search(nom)}
        self.assertIn("JWT_SECRET", secrets)
        self.assertIn("POSTGRES_PASSWORD", secrets)
        for nom, valeur in secrets.items():
            with self.subTest(variable=nom):
                self.assertTrue(valeur.startswith(dev.PLACEHOLDER), f"{nom} porte une vraie valeur")

    def test_les_reglages_de_securite_ne_sont_pas_des_secrets(self):
        for nom in ("CORS_ALLOWED_ORIGINS", "LOGIN_ATTEMPTS_PER_MINUTE", "LOGIN_MAX_FAILURES",
                    "LOGIN_LOCKOUT_S", "TRUSTED_PROXY_HOPS"):
            with self.subTest(variable=nom):
                self.assertIn(nom, self.variables)
                self.assertNotIn(dev.PLACEHOLDER, self.variables[nom])

    def test_cors_n_autorise_aucun_joker_ni_chemin(self):
        origines = [o.strip() for o in self.variables["CORS_ALLOWED_ORIGINS"].split(",") if o.strip()]
        self.assertTrue(origines)
        for origine in origines:
            with self.subTest(origine=origine):
                self.assertRegex(origine, r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$")

    def test_aucune_adresse_de_connexion_n_a_de_mot_de_passe_ecrit(self):
        self.assertIsNone(URL_AVEC_MOT_DE_PASSE.search(self.texte))


class EnvGenere(unittest.TestCase):
    def setUp(self):
        self.exemple = (RACINE / ".env.example").read_text(encoding="utf-8")

    def test_aucune_valeur_d_exemple_ne_survit_a_la_generation(self):
        genere, nombre = dev.generate_env(self.exemple)
        self.assertGreater(nombre, 10)
        for nom, valeur in affectations(genere):  # la consigne en commentaire peut citer la valeur
            with self.subTest(variable=nom):
                self.assertNotIn(dev.PLACEHOLDER, valeur)

    def test_les_secrets_sont_aleatoires_longs_et_differents_a_chaque_generation(self):
        premier = dev.parse_env(dev.generate_env(self.exemple)[0])
        second = dev.parse_env(dev.generate_env(self.exemple)[0])
        for nom, valeur in premier.items():
            if NOM_SECRET.search(nom):
                with self.subTest(variable=nom):
                    self.assertGreaterEqual(len(valeur), 32 if nom == "JWT_SECRET" else 24)
                    self.assertNotEqual(valeur, second[nom])
                    self.assertRegex(valeur, r"^[A-Za-z0-9_-]+$")
        secrets = [v for n, v in premier.items() if NOM_SECRET.search(n)]
        self.assertEqual(len(secrets), len(set(secrets)), "deux secrets ne partagent jamais une valeur")

    def test_les_reglages_qui_ne_sont_pas_des_secrets_restent_ceux_de_l_exemple(self):
        exemple = dev.parse_env(self.exemple)
        genere = dev.parse_env(dev.generate_env(self.exemple)[0])
        for nom in ("CORS_ALLOWED_ORIGINS", "LOGIN_MAX_FAILURES", "TRUSTED_PROXY_HOPS", "POSTGRES_USER"):
            with self.subTest(variable=nom):
                self.assertEqual(genere[nom], exemple[nom])

    def test_le_fichier_est_cree_en_lecture_reservee_et_sans_afficher_les_valeurs(self):
        source = (RACINE / "scripts" / "dev" / "dev.py").read_text(encoding="utf-8")
        self.assertIn("0o600", source)
        self.assertIn("jamais affichées", source)


class ConfigurationSansSecretEcrit(unittest.TestCase):
    FICHIERS = (r"(^|/)docker-compose\.yml$", r"(^|/)compose\.[\w.-]+\.yml$", r"(^|/)Dockerfile$",
                r"\.github/workflows/.*\.yml$")

    def test_les_fichiers_a_controler_existent(self):
        self.assertGreaterEqual(len(fichiers_suivis(*self.FICHIERS)), 8)

    def test_une_variable_secrete_est_une_reference_jamais_une_valeur(self):
        for fichier in fichiers_suivis(*self.FICHIERS):
            for nom, valeur in affectations(fichier.read_text(encoding="utf-8")):
                if NOM_SECRET.search(nom) and not nom.startswith("GIT"):
                    with self.subTest(fichier=fichier.relative_to(RACINE).as_posix(), variable=nom):
                        self.assertRegex(valeur, REFERENCE, f"{nom} reçoit une valeur écrite")

    def test_aucune_adresse_de_connexion_n_a_de_mot_de_passe_ecrit(self):
        for fichier in fichiers_suivis(*self.FICHIERS, r"infra/ecs/.*\.json$"):
            for numero, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
                for trouve in URL_AVEC_MOT_DE_PASSE.finditer(ligne):
                    with self.subTest(fichier=fichier.name, ligne=numero):
                        self.assertTrue(trouve.group(1).startswith("${"), f"mot de passe écrit ligne {numero}")

    def test_les_taches_ecs_lisent_leurs_secrets_dans_un_gestionnaire_pas_dans_l_environnement(self):
        for fichier in fichiers_suivis(r"infra/ecs/.*\.json$"):
            tache = json.loads(fichier.read_text(encoding="utf-8"))
            for conteneur in tache["containerDefinitions"]:
                for variable in conteneur.get("environment", []):
                    with self.subTest(fichier=fichier.name, variable=variable["name"]):
                        self.assertIsNone(NOM_SECRET.search(variable["name"]),
                                          "un secret passe par `secrets`, pas par `environment`")
                for secret in conteneur.get("secrets", []):
                    with self.subTest(fichier=fichier.name, secret=secret["name"]):
                        self.assertRegex(secret["valueFrom"], r"^arn:aws:(ssm|secretsmanager):")

    def test_compose_ne_donne_a_traitement_aucune_valeur_de_secret_ecrite(self):
        texte = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        bloc = texte[texte.index("\n  traitement:"):texte.index("\n  alerte:")]
        valeurs = dict(affectations(bloc))
        self.assertEqual(valeurs["JWT_SECRET"], "${JWT_SECRET:-}")
        self.assertTrue(valeurs["CORS_ALLOWED_ORIGINS"].endswith(":-}"), "CORS fermé quand rien n'est configuré")


if __name__ == "__main__":
    unittest.main()
