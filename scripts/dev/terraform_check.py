"""Contrôles Terraform sans compte AWS (LOC-06) : format, init sans état distant, validate, tflint, Snyk IaC.

Chaque outil tourne dans un conteneur à version fixée : seul Docker est requis, avec les mêmes commandes et les mêmes
résultats sous Linux et sous Windows. Le dépôt est monté en lecture seule ; aucune variable AWS n'est transmise.
La logique est ici (testable sans Docker) ; `dev.py terraform-check` ne fait que l'appeler."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

TERRAFORM_IMAGE = "hashicorp/terraform:1.17.0"
TFLINT_IMAGE = "ghcr.io/terraform-linters/tflint:v0.65.0"
# Snyk CLI 1.1308.4 ; le résumé fixe l'image (l'étiquette « alpine » avance à chaque version).
SNYK_IMAGE = "snyk/snyk:alpine@sha256:0a334ca2677ef43eabc1206724a1de7154d9b0d6d7b31be3639b03422edcc06d"
CACHE_VOLUME = "novaria-terraform-cache"  # fournisseurs Terraform et plugins tflint, pour ne les télécharger qu'une fois
# Les outils tournent dans des conteneurs Linux, y compris avec Docker Desktop sous Windows : une seule empreinte suffit.
# Un poste ARM (conteneurs linux_arm64) devrait ajouter sa plateforme ici ; chaque plateforme ajoutée télécharge le fournisseur (≈ 180 Mo).
LOCK_PLATFORMS = ("linux_amd64",)
SNYK_SEVERITY = "high"  # même seuil que le job snyk de la CI

OK, KO, SKIPPED = "OK", "KO", "SAUTÉ"


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    skip_reason: str | None = None  # renseigné : l'étape n'est pas lancée et le résultat n'est pas « réussi »


@dataclass
class Result:
    step: Step
    status: str
    seconds: float = 0.0
    output: str = field(default="", repr=False)


class TerraformCheckError(Exception):
    pass


def environments(root: Path) -> list[str]:
    """Environnements de envs/ qui contiennent au moins un fichier .tf."""
    envs = root / "envs"
    if not envs.is_dir():
        return []
    return sorted(p.name for p in envs.iterdir() if p.is_dir() and any(p.glob("*.tf")))


def docker_run(image: str, *args: str, mounts: Sequence[tuple[str, str]] = (), workdir: str = "/w",
               env: Mapping[str, str | None] | None = None, entrypoint: str | None = None, user: str | None = None) -> list[str]:
    """`docker run --rm` sans shell. Une variable d'environnement sans valeur (« SNYK_TOKEN ») est lue dans le processus appelant."""
    command = ["docker", "run", "--rm"]
    if user:
        command += ["--user", user]
    for name, value in (env or {}).items():
        command += ["-e", f"{name}={value}" if value is not None else name]
    for source, target in mounts:
        command += ["-v", f"{source}:{target}"]
    if entrypoint:
        command += ["--entrypoint", entrypoint]
    return [*command, "-w", workdir, image, *args]


def terraform_command(root: Path, *args: str, env_name: str | None = None, shell: str | None = None) -> list[str]:
    """Une commande Terraform dans le conteneur ; l'état d'initialisation vit dans le volume de cache, jamais dans le dépôt."""
    workdir = f"/w/envs/{env_name}" if env_name else "/w"
    variables = {"TF_IN_AUTOMATION": "1", "TF_DATA_DIR": f"/cache/data/{env_name or 'racine'}"}
    if shell is not None:  # le cache des fournisseurs n'existe qu'après le « mkdir -p » de l'initialisation
        variables["TF_PLUGIN_CACHE_DIR"] = "/cache/plugins"
    mounts = [(str(root), "/w:ro"), (CACHE_VOLUME, "/cache")]
    if shell is not None:
        return docker_run(TERRAFORM_IMAGE, "-c", shell, mounts=mounts, workdir=workdir, env=variables, entrypoint="sh")
    return docker_run(TERRAFORM_IMAGE, *args, "-no-color", mounts=mounts, workdir=workdir, env=variables)


def tflint_command(root: Path, *args: str) -> list[str]:
    return docker_run(TFLINT_IMAGE, *args, mounts=[(str(root), "/w:ro"), (CACHE_VOLUME, "/cache")],
                      env={"TFLINT_PLUGIN_DIR": "/cache/tflint"})


def snyk_command(root: Path) -> list[str]:
    return docker_run(SNYK_IMAGE, "snyk", "iac", "test", ".", f"--severity-threshold={SNYK_SEVERITY}",
                      mounts=[(str(root), "/app:ro")], workdir="/app", env={"SNYK_TOKEN": None})


def build_steps(root: Path, *, snyk_token: bool = True, with_snyk: bool = True) -> list[Step]:
    """Les contrôles de l'issue LOC-06, dans l'ordre : fmt, puis init et validate par environnement, puis tflint, puis Snyk IaC."""
    names = environments(root)
    if not names:
        raise TerraformCheckError(f"Aucun environnement Terraform dans {root / 'envs'} (dossier envs/<nom>/ avec des fichiers .tf).")
    steps = [Step("terraform fmt", terraform_command(root, "fmt", "-check", "-recursive", "-diff"))]
    for name in names:
        steps.append(Step(f"terraform init ({name})", terraform_command(
            root, env_name=name, shell="mkdir -p /cache/plugins && terraform init -backend=false -input=false -lockfile=readonly -no-color")))
        steps.append(Step(f"terraform validate ({name})", terraform_command(root, "validate", env_name=name)))
    steps.append(Step("tflint (extensions)", tflint_command(root, "--init", "--config", "/w/.tflint.hcl")))
    steps.append(Step("tflint", tflint_command(root, "--recursive", "--config", "/w/.tflint.hcl", "--format", "compact")))
    if with_snyk:
        reason = None if snyk_token else "SNYK_TOKEN absent (variable d'environnement ou .env) : compte Snyk gratuit, aucun lien avec AWS"
        steps.append(Step("snyk iac", snyk_command(root), skip_reason=reason))
    return steps


def lock_steps(root: Path, user: str | None) -> list[Step]:
    """Régénère .terraform.lock.hcl de chaque environnement pour les plateformes de LOCK_PLATFORMS (écrit dans le dépôt)."""
    platforms = " ".join(f"-platform={p}" for p in LOCK_PLATFORMS)
    script = f"terraform init -backend=false -input=false -no-color && terraform providers lock -no-color {platforms}"
    steps = []
    for name in environments(root):
        command = docker_run(TERRAFORM_IMAGE, "-c", script, mounts=[(str(root), "/w")], workdir=f"/w/envs/{name}",
                             env={"TF_IN_AUTOMATION": "1", "TF_DATA_DIR": "/tmp/tfdata"}, entrypoint="sh", user=user)
        steps.append(Step(f"verrou des fournisseurs ({name})", command))
    return steps


def run_steps(steps: Sequence[Step], run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
              env: Mapping[str, str] | None = None, echo: Callable[[str], None] = print, verbose: bool = False) -> list[Result]:
    """Lance les étapes l'une après l'autre (toutes, même après un échec) ; la sortie n'est montrée que si l'étape échoue ou avec verbose."""
    results = []
    for step in steps:
        if step.skip_reason:
            echo(f"  [{SKIPPED}] {step.name} : {step.skip_reason}")
            results.append(Result(step, SKIPPED))
            continue
        started = time.monotonic()
        try:
            done = run(step.command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=env)
        except OSError as error:
            raise TerraformCheckError(f"Docker est introuvable ou inutilisable : {error}") from error
        output = ((done.stdout or "") + (done.stderr or "")).strip()
        status = OK if done.returncode == 0 else KO
        result = Result(step, status, time.monotonic() - started, output)
        results.append(result)
        echo(f"  [{status}] {step.name} ({result.seconds:.0f} s)")
        if output and (status == KO or verbose):
            echo("\n".join(f"      {line}" for line in output.splitlines()[-60:]))
    return results


def exit_code(results: Sequence[Result]) -> int:
    """0 : tout a réussi ; 1 : une étape a échoué ; 2 : rien n'a échoué mais une étape n'a pas été lancée (le contrôle est incomplet)."""
    if any(r.status == KO for r in results):
        return 1
    return 2 if any(r.status == SKIPPED for r in results) else 0


def process_environment(token: str | None, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environnement du processus docker : celui de l'appelant sans aucune variable AWS_*, plus SNYK_TOKEN s'il est connu."""
    env = {k: v for k, v in (base if base is not None else os.environ).items() if not k.upper().startswith("AWS_")}
    if token:
        env["SNYK_TOKEN"] = token
    return env
