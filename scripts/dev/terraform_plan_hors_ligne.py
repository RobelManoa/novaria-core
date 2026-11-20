"""Plans Terraform **hors ligne** (CLD-17) : ce que le code créerait, et ce que ses protections refusent de détruire. Sans compte AWS.

Un vrai second plan « à 0 changement » exige un état créé par un `apply`, donc un compte AWS : il est différé (ADR-023). Ce qui se
fait sans compte, dans un conteneur et sur une **copie jetable** de `infra/terraform/` (le dépôt n'est jamais modifié) :

| Mode | Ce que Terraform montre | Attendu |
|---|---|---|
| `plan` | le premier plan, état vide : les ressources qui seraient créées | « Plan: 15 to add » ; aucune connexion à AWS |
| `destruction-protegee` | `plan -destroy` sur un **état fictif** qui contient un dépôt ECR protégé | refus : « Instance cannot be destroyed » (code 1) |
| `bascule-variable` | le même état fictif, avec `protected = false` dans la copie | **toujours refusé** : le bloc protégé reste dans le module, basculer la variable ne lève pas la protection |

Garanties : identifiants **factices** dans la copie seulement (jamais dans le dépôt) ; `skip_credentials_validation`,
`skip_requesting_account_id` et `skip_metadata_api_check` : le fournisseur ne contacte pas AWS ; aucune variable `AWS_*` n'est
transmise au conteneur. L'état fictif n'est **pas** une preuve d'idempotence : aucun `apply` n'a eu lieu.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from terraform_check import CACHE_VOLUME, TERRAFORM_IMAGE, docker_run, process_environment

MODES = ("plan", "destruction-protegee", "bascule-variable")
OVERRIDE_NOM = "zz_hors_ligne_override.tf"
OVERRIDE = '''# Copie jetable, jamais versionnée : plan hors ligne. Les identifiants sont factices et AWS n'est jamais contacté (aucun appel d'API).
provider "aws" {
  access_key                  = "factice"
  secret_key                  = "factice"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}
'''
COMPTE_FICTIF = "000000000000"


def etat_fictif(prefixe: str = "novaria-dev", service: str = "alerte") -> dict:
    """Un état Terraform (version 4) minimal : un seul dépôt ECR protégé, sur un compte fictif. Ce n'est le résultat d'aucun `apply`."""
    nom = f"{prefixe}-{service}"
    attributs = {
        "arn": f"arn:aws:ecr:eu-west-1:{COMPTE_FICTIF}:repository/{nom}", "encryption_configuration": [{"encryption_type": "AES256", "kms_key": ""}],
        "force_delete": False, "id": nom, "image_scanning_configuration": [{"scan_on_push": True}], "image_tag_mutability": "IMMUTABLE", "name": nom,
        "registry_id": COMPTE_FICTIF, "repository_url": f"{COMPTE_FICTIF}.dkr.ecr.eu-west-1.amazonaws.com/{nom}", "tags": None, "tags_all": {}, "timeouts": None,
    }
    return {"version": 4, "terraform_version": "1.17.0", "serial": 1, "lineage": "00000000-0000-0000-0000-00000000fict", "outputs": {},
            "resources": [{"module": "module.ecr", "mode": "managed", "type": "aws_ecr_repository", "name": "protected",
                           "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
                           "instances": [{"index_key": service, "schema_version": 0, "attributes": attributs, "sensitive_attributes": []}]}],
            "check_results": None}


def preparer_copie(source: Path, cible: Path, mode: str, env_name: str = "dev") -> Path:
    """Copie `source` (infra/terraform) dans `cible`, y ajoute le fournisseur factice, et selon le mode l'état fictif et la bascule de la variable `protected`."""
    if mode not in MODES:
        raise ValueError(f"mode inconnu : {mode!r} (attendus : {', '.join(MODES)})")
    shutil.copytree(source, cible, ignore=shutil.ignore_patterns(".terraform", "terraform.tfstate*"))
    env_dir = cible / "envs" / env_name
    (env_dir / OVERRIDE_NOM).write_text(OVERRIDE, encoding="utf-8", newline="\n")
    if mode != "plan":
        (env_dir / "terraform.tfstate").write_text(json.dumps(etat_fictif(f"novaria-{env_name}"), indent=1), encoding="utf-8", newline="\n")
    if mode == "bascule-variable":
        principal = env_dir / "main.tf"
        texte, nombre = re.subn(r"(?m)^(\s*protected\s*=\s*)true(\s*#.*dépôts)", r"\1false\2", principal.read_text(encoding="utf-8"), count=1)
        if nombre != 1:
            raise ValueError(f"{principal} : la ligne « protected = true » du module ecr est introuvable")
        principal.write_text(texte, encoding="utf-8", newline="\n")
    return env_dir


def commande(copie: Path, env_name: str, mode: str) -> list[str]:
    """La commande Docker : initialisation sans état distant (verrou en lecture seule), puis le plan du mode."""
    plan = "terraform plan -input=false -lock=false -no-color"
    if mode == "destruction-protegee":
        plan = "terraform plan -destroy -refresh=false -input=false -lock=false -no-color"
    elif mode == "bascule-variable":
        plan = "terraform plan -refresh=false -input=false -lock=false -no-color"
    script = f"mkdir -p /cache/plugins && terraform init -backend=false -input=false -lockfile=readonly -no-color >/dev/null && {plan}"
    variables = {"TF_IN_AUTOMATION": "1", "TF_DATA_DIR": f"/cache/data/hors-ligne-{env_name}", "TF_PLUGIN_CACHE_DIR": "/cache/plugins"}
    return docker_run(TERRAFORM_IMAGE, "-c", script, mounts=[(str(copie.parent.parent), "/w"), (CACHE_VOLUME, "/cache")], workdir=f"/w/envs/{env_name}",
                      env=variables, entrypoint="sh")


def executer(racine: Path, mode: str, env_name: str, temporaire: Path, run: Callable[..., subprocess.CompletedProcess] | None = None) -> tuple[int, str]:
    """Rend (code de sortie de Terraform, sortie). La copie jetable vit dans `temporaire` et n'est pas supprimée ici."""
    copie = temporaire / "terraform"
    env_dir = preparer_copie(racine, copie, mode, env_name)
    run = run or subprocess.run
    fait = run(commande(env_dir, env_name, mode), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=process_environment(None))
    return fait.returncode, ((fait.stdout or "") + (fait.stderr or "")).strip()


def verdict(mode: str, code: int, sortie: str) -> list[str]:
    """Ce qu'on attend de chaque mode ; la liste des écarts est vide quand tout est conforme."""
    if mode == "plan":
        ecarts = [] if code == 0 and re.search(r"Plan: 15 to add, 0 to change, 0 to destroy", sortie) else ["« Plan: 15 to add, 0 to change, 0 to destroy » attendu"]
    elif mode == "destruction-protegee":
        ecarts = [] if code != 0 and "Instance cannot be destroyed" in sortie and "prevent_destroy" in sortie else ["le refus « Instance cannot be destroyed » est attendu"]
    else:
        ecarts = [] if code != 0 and "will be destroyed" in sortie and "Instance cannot be destroyed" in sortie else ["la bascule de `protected` ne doit pas lever le refus de destruction"]
    return ecarts
