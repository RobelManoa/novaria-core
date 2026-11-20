"""Terraform contre un émulateur d'API AWS **local et ouvert** (Moto) : appliquer, puis rejouer le plan (CLD-17), sans compte AWS.

Pourquoi Moto : licence Apache-2.0, projet de 2013 toujours publié (5.2.5 le 27/10/2026), image Docker officielle, ECR et CloudWatch
Logs gérés. LocalStack n'est plus un choix stable : depuis le 23/03/2026 son image exige un compte et un jeton, et l'édition
communautaire n'est plus entretenue ([annonce](https://blog.localstack.cloud/the-road-ahead-for-localstack/)).

Le **même code** Terraform (`infra/terraform/envs/<env>`) s'applique à l'émulateur : seule une copie jetable reçoit un fichier qui
redirige les adresses d'API vers `http://moto:5000`. Garanties :

- l'émulateur et Terraform tournent sur un réseau Docker **interne** (`--internal`) : aucune route vers Internet, donc aucun appel
  possible vers le vrai AWS, même avec une adresse mal écrite (un essai l'a montré : le fournisseur tentait `iam.amazonaws.com`) ;
- seule l'étape `init` utilise le réseau normal (fournisseur et registre) ; ensuite plus rien ne sort ;
- identifiants **factices**, dans la copie seulement ; aucune variable `AWS_*` n'entre dans un conteneur ;
- aucun port n'est publié sur le poste ; l'émulateur tourne sans droits (`--user 65534`, `--cap-drop ALL`, système de fichiers en lecture seule) ;
- l'image est fixée par son **empreinte**.

Ce que cela prouve : le code est **idempotent** (l'application suivie du plan donne « No changes ») et ses protections jouent sur un
vrai état. Ce que cela ne prouve pas : le comportement du vrai AWS (quotas, droits, valeurs refusées par le service).
"""

from __future__ import annotations

import re
import secrets
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from terraform_check import CACHE_VOLUME, TERRAFORM_IMAGE, process_environment

IMAGE_EMULATEUR = "motoserver/moto@sha256:59a1965d845249b04def37a0e2565f9cc6c44543cb89b68e90f28f344b3b0d1a"  # Moto 5.2.5, publiée le 27/10/2026
ADRESSE = "http://moto:5000"
OVERRIDE_NOM = "zz_emulateur_override.tf"
OVERRIDE = f'''# Copie jetable, jamais versionnée : les adresses d'API pointent vers l'émulateur local. Identifiants factices.
provider "aws" {{
  access_key                  = "factice"
  secret_key                  = "factice"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true

  endpoints {{
    ecr  = "{ADRESSE}"
    logs = "{ADRESSE}"
  }}
}}
'''
SERVICES = 5  # dépôts, politiques et groupes de journaux : 3 ressources par service
RESSOURCES = 3 * SERVICES
ENTETES_LOGS = ("--header='Content-Type: application/x-amz-json-1.1' "
                "--header='Authorization: AWS4-HMAC-SHA256 Credential=factice/20261119/eu-west-1/logs/aws4_request, SignedHeaders=host, Signature=x'")


@dataclass(frozen=True)
class Etape:
    nom: str
    script: str
    reseau_interne: bool  # vrai : sur le réseau sans route vers Internet
    verifier: Callable[[int, str], list[str]]  # (code, sortie) -> écarts


@dataclass
class Resultat:
    etape: Etape
    code: int
    sortie: str
    ecarts: list[str]

    @property
    def ok(self) -> bool:
        return not self.ecarts


def appel_logs(action: str, corps: str) -> str:
    """Un appel JSON à l'API CloudWatch Logs de l'émulateur, depuis le conteneur Terraform (wget de BusyBox)."""
    return f"wget -q -O - {ENTETES_LOGS} --header='X-Amz-Target: Logs_20140328.{action}' --post-data='{corps}' {ADRESSE}/"


def contient(*motifs: str, code: int | None = None, absent: tuple[str, ...] = ()) -> Callable[[int, str], list[str]]:
    def verifier(c: int, sortie: str) -> list[str]:
        ecarts = [f"« {m} » absent de la sortie" for m in motifs if not re.search(m, sortie)]
        ecarts += [f"« {m} » présent dans la sortie" for m in absent if re.search(m, sortie)]
        if code is not None and c != code:
            ecarts.append(f"code de sortie {c}, {code} attendu")
        return ecarts
    return verifier


def refus_attendu(c: int, sortie: str) -> list[str]:
    ecarts = [] if "Instance cannot be destroyed" in sortie and "prevent_destroy" in sortie else ["le refus « Instance cannot be destroyed » est attendu"]
    return ecarts + ([] if c != 0 else ["la commande devait échouer"])


def scenario(env_name: str) -> list[Etape]:
    """Les étapes d'un environnement. `dev` est protégé (la destruction est refusée), `demo` est jetable (elle réussit)."""
    prefixe = f"/novaria/{env_name}/"
    etapes = [
        Etape("init (réseau normal : fournisseur depuis le cache ou le registre)", "mkdir -p /cache/plugins && terraform init -backend=false -input=false -lockfile=readonly -no-color",
              False, contient("Terraform has been successfully initialized", code=0)),
        Etape("apply : création dans l'émulateur", "terraform apply -auto-approve -input=false -no-color", True,
              contient(rf"Apply complete! Resources: {RESSOURCES} added, 0 changed, 0 destroyed", code=0)),
        Etape("SECOND PLAN : doit indiquer 0 changement", "terraform plan -detailed-exitcode -input=false -no-color", True,
              contient(r"No changes\. Your infrastructure matches the configuration", code=0)),
        Etape("dérive : un groupe de journaux est modifié hors Terraform (30 jours au lieu de la valeur du code)",
              appel_logs("PutRetentionPolicy", f'{{"logGroupName":"{prefixe}alerte","retentionInDays":30}}'), True, contient(code=0)),
        Etape("plan après la dérive : doit voir 1 changement (le contrôle sait échouer)", "terraform plan -detailed-exitcode -input=false -no-color", True,
              contient(r"Plan: 0 to add, 1 to change, 0 to destroy", code=2)),
        Etape("apply de correction", "terraform apply -auto-approve -input=false -no-color", True,
              contient(r"Apply complete! Resources: 0 added, 1 changed, 0 destroyed", code=0)),
        Etape("SECOND PLAN après correction : de nouveau 0 changement", "terraform plan -detailed-exitcode -input=false -no-color", True,
              contient(r"No changes\. Your infrastructure matches the configuration", code=0)),
    ]
    if env_name == "dev":
        etapes += [
            Etape("destroy complet : refusé (dépôts protégés, sur un vrai état)", "terraform destroy -auto-approve -input=false -no-color", True, refus_attendu),
            Etape("destroy des journaux seuls (skip_destroy) : ils sortent de l'état", "terraform destroy -target=module.observability -auto-approve -input=false -no-color", True,
                  contient(rf"Destroy complete! Resources: {SERVICES} destroyed", code=0)),
            Etape("les journaux existent toujours dans l'émulateur", appel_logs("DescribeLogGroups", f'{{"logGroupNamePrefix":"{prefixe}"}}'), True,
                  lambda c, s: [] if len(re.findall(r'"logGroupName"', s)) == SERVICES and c == 0 else [f"{len(re.findall(chr(34) + 'logGroupName' + chr(34), s))} groupe(s) au lieu de {SERVICES}"]),
        ]
    else:
        etapes += [
            Etape("destroy complet : réussit (environnement jetable)", "terraform destroy -auto-approve -input=false -no-color", True,
                  contient(rf"Destroy complete! Resources: {RESSOURCES} destroyed", code=0)),
            Etape("les journaux ont disparu de l'émulateur", appel_logs("DescribeLogGroups", f'{{"logGroupNamePrefix":"{prefixe}"}}'), True,
                  lambda c, s: [] if '"logGroupName"' not in s and c == 0 else ["des groupes de journaux existent encore"]),
        ]
    return etapes


def preparer_copie(source: Path, cible: Path, env_name: str) -> Path:
    shutil.copytree(source, cible, ignore=shutil.ignore_patterns(".terraform", "terraform.tfstate*"))
    dossier = cible / "envs" / env_name
    (dossier / OVERRIDE_NOM).write_text(OVERRIDE, encoding="utf-8", newline="\n")
    return dossier


def commande_terraform(copie_racine: Path, env_name: str, script: str, reseau: str | None) -> list[str]:
    """Un conteneur Terraform sur la copie (en écriture) ; sans aucune variable AWS_*, sur le réseau interne quand `reseau` est donné."""
    commande = ["docker", "run", "--rm"]
    if reseau:
        commande += ["--network", reseau]
    for nom, valeur in (("CHECKPOINT_DISABLE", "1"), ("TF_IN_AUTOMATION", "1"), ("TF_DATA_DIR", f"/cache/data/emulateur-{env_name}"), ("TF_PLUGIN_CACHE_DIR", "/cache/plugins")):
        commande += ["-e", f"{nom}={valeur}"]
    commande += ["-v", f"{copie_racine}:/w", "-v", f"{CACHE_VOLUME}:/cache", "-w", f"/w/envs/{env_name}", "--entrypoint", "sh", TERRAFORM_IMAGE, "-c", script]
    return commande


def commande_emulateur(reseau: str, nom: str) -> list[str]:
    return ["docker", "run", "-d", "--rm", "--name", nom, "--network", reseau, "--network-alias", "moto", "--user", "65534:65534", "--read-only",
            "--tmpfs", "/tmp", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", IMAGE_EMULATEUR]


def _docker(args: list[str], run, check: bool = False):
    return run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check, env=process_environment(None))


def executer(racine: Path, env_name: str, temporaire: Path, run: Callable[..., subprocess.CompletedProcess] | None = None,
             attendre_emulateur: Callable[[str], None] | None = None) -> list[Resultat]:
    """Joue le scénario. Le réseau et l'émulateur sont **toujours** supprimés, même après une erreur. Une étape qui échoue n'arrête pas les suivantes
    qui n'en dépendent pas : seul `init` en échec interrompt tout (rien ne peut s'appliquer)."""
    run = run or subprocess.run
    copie = temporaire / "terraform"
    preparer_copie(racine, copie, env_name)
    suffixe = secrets.token_hex(3)
    reseau, nom = f"novaria-tf-emu-{suffixe}", f"moto-{suffixe}"
    resultats: list[Resultat] = []
    try:
        cree = _docker(["docker", "network", "create", "--internal", reseau], run)
        if cree.returncode:
            raise RuntimeError(f"réseau Docker non créé : {(cree.stderr or cree.stdout).strip()[-200:]}")
        demarre = _docker(commande_emulateur(reseau, nom), run)
        if demarre.returncode:
            raise RuntimeError(f"émulateur non démarré : {(demarre.stderr or demarre.stdout).strip()[-200:]}")
        (attendre_emulateur or (lambda n: _attendre(copie, env_name, reseau, run)))(nom)
        for etape in scenario(env_name):
            fait = _docker(commande_terraform(copie, env_name, etape.script, reseau if etape.reseau_interne else None), run)
            sortie = ((fait.stdout or "") + (fait.stderr or "")).strip()
            resultat = Resultat(etape, fait.returncode, sortie, etape.verifier(fait.returncode, sortie))
            resultats.append(resultat)
            if etape.nom.startswith("init") and resultat.ecarts:
                break
    finally:
        _docker(["docker", "rm", "-f", nom], run)
        _docker(["docker", "network", "rm", reseau], run)
    return resultats


def _attendre(copie: Path, env_name: str, reseau: str, run, essais: int = 30) -> None:
    script = f"for i in $(seq 1 {essais}); do wget -q -O /dev/null -T 2 {ADRESSE}/moto-api/ && exit 0; sleep 1; done; exit 1"
    if _docker(commande_terraform(copie, env_name, script, reseau), run).returncode:
        raise RuntimeError(f"l'émulateur ne répond pas sur {ADRESSE} après {essais} s")


def verdict(resultats: list[Resultat]) -> list[str]:
    """Une ligne par étape en écart ; vide quand tout est conforme."""
    return [f"{r.etape.nom} : {'; '.join(r.ecarts)}" for r in resultats if r.ecarts]


def transcription(resultats: list[Resultat], env_name: str, date: str = "") -> str:
    """Le compte rendu de l'exécution, étape par étape, avec la sortie de chaque commande telle quelle."""
    lignes = [f"# Terraform appliqué à l'émulateur d'API AWS Moto (local, Apache-2.0), environnement {env_name}, puis plan rejoué. AWS n'est pas contacté.",
              f"# Commande : python3 scripts/dev/dev.py terraform-emulateur --env {env_name} --sortie <fichier>",
              f"# Date : {date or 'non renseignée'} · Terraform {TERRAFORM_IMAGE.rsplit(':', 1)[-1]} · image de l'émulateur {IMAGE_EMULATEUR.split('@')[0]}@{IMAGE_EMULATEUR.split('@')[1][:19]}…",
              "# Réseau Docker interne, identifiants factices. C'est un ÉMULATEUR : ces sorties ne prouvent rien sur le comportement du vrai AWS.",
              "# Sortie de chaque commande, sans modification :", ""]
    for i, r in enumerate(resultats, start=1):
        lignes += [f"## Étape {i} : {r.etape.nom}", f"## Code de sortie : {r.code} · {'conforme' if r.ok else 'ÉCART : ' + '; '.join(r.ecarts)}", "", r.sortie, "", ""]
    return "\n".join(lignes)
