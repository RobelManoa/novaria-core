#!/usr/bin/env python3
"""Crée labels, jalons et issues du projet Novaria Core avec GitHub CLI (gh).

Usage :
  python scripts/github/bootstrap.py --dry-run          # affiche ce qui serait créé
  python scripts/github/bootstrap.py --create           # crée tout (idempotent : relançable)

Linux : python3 scripts/github/bootstrap.py --dry-run     Windows : py -3 scripts/github/bootstrap.py --dry-run
Variables facultatives : DADDY_GH et MANOA_GH (identifiants GitHub) pour assigner les issues.
Prérequis : `gh auth login` effectué, dépôt courant relié à GitHub.
Pour les issues ajoutées ou amendées après la première création, voir sync_backlog.py.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

for _flux in (sys.stdout, sys.stderr):  # accents corrects sous Windows (console en page de codes locale)
    if hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from issues_data import BC05, ISSUES, MILESTONES, PRIOS, TEAMS, TYPES  # noqa: E402

LEVEL = {"bigdata": "Prototype ciblé", "flux": "Prototype ciblé", "rpa": "Prototype ciblé"}
OWNERS = {"D": "Daddy Luciano", "M": "Manoa Robel", "DM": "Daddy Luciano et Manoa Robel (relecture croisée)"}


def gh(*args, dry=False, capture=True, input_text=None):
    """Appelle `gh` sans passer par un shell. Le texte long (corps d'issue) passe par l'entrée standard en UTF-8."""
    if dry:
        print("  $ gh " + " ".join(args))
        return ""
    exe = shutil.which("gh")
    if exe is None:
        sys.exit("GitHub CLI (gh) introuvable : l'installer puis lancer `gh auth login`.")
    result = subprocess.run([exe, *args], check=True, capture_output=capture, input=input_text,
                            text=True, encoding="utf-8")
    return result.stdout


def issue_id(title):
    """Identifiant de backlog d'un titre d'issue, par exemple `[CLD-01] ...` -> `CLD-01`."""
    m = re.match(r"\[([A-Z]+-\d+)\]", title)
    return m.group(1) if m else None


def existing_issues():
    """{identifiant: {number, title, body, labels}} pour toutes les issues déjà présentes sur GitHub."""
    out = {}
    raw = gh("issue", "list", "--state", "all", "--limit", "1000", "--json", "number,title,body,labels")
    for i in json.loads(raw):
        key = issue_id(i["title"])
        if key:
            out[key] = dict(number=i["number"], title=i["title"], body=i.get("body") or "",
                            labels=[lab["name"] for lab in i.get("labels", [])])
    return out


def labels():
    out = []
    for key, (name, color) in TEAMS.items():
        out.append((f"team:{key}", color, name))
    for key, desc in TYPES.items():
        out.append((f"type:{key}", "64748B", desc))
    for key, color in PRIOS.items():
        out.append((f"prio:{key}", color, "Priorité"))
    for key, desc in BC05.items():
        out.append((f"bc05:{key}", "E8512F", desc))
    return out


def render_body(issue, numbers):
    lines = [f"**Équipe** : {TEAMS[issue['team']][0]} · **Responsable** : {OWNERS[issue['owner']]} · **Priorité** : {issue['prio']}", ""]
    if issue["bc05"]:
        comp = ", ".join(f"{BC05[k]} ({LEVEL.get(k, 'Implémenté')})" for k in issue["bc05"][:3])
        suffix = " …" if len(issue["bc05"]) > 3 else ""
        lines += [f"**Compétence BC05** : {comp}{suffix}", ""]
    lines += ["## Tâches", *[f"- [ ] {t}" for t in issue["tasks"]], "", "## Critère d'acceptation", issue["done"], ""]
    if issue["proof"]:
        lines += ["## Preuve attendue", issue["proof"], ""]
    deps = [f"#{numbers[d]}" for d in issue["deps"] if d in numbers]
    if deps:
        lines += ["## Dépend de", ", ".join(deps), ""]
    lines += [f"<sub>Réf. backlog : {issue['id']}</sub>"]
    return "\n".join(lines)


def ensure_labels(extra=(), dry=False):
    allv = [*labels(), *extra]
    print(f"Labels ({len(allv)})")
    for name, color, desc in allv:
        gh("label", "create", name, "--color", color, "--description", desc[:100], "--force", dry=dry)


def ensure_milestones(dry=False):
    print(f"Jalons ({len(MILESTONES)})")
    existing_ms = set()
    if not dry:
        existing_ms = {m["title"] for m in json.loads(gh("api", "repos/{owner}/{repo}/milestones?state=all&per_page=100"))}
    for title, due, desc in MILESTONES:
        if title in existing_ms:
            continue
        gh("api", "repos/{owner}/{repo}/milestones", "-f", f"title={title}", "-f", f"due_on={due}T23:59:59Z",
           "-f", f"description={desc}", dry=dry)


def issue_labels(issue):
    return [f"team:{issue['team']}", f"type:{issue['type']}", f"prio:{issue['prio']}", *[f"bc05:{k}" for k in issue["bc05"]]]


def create_issue(issue, numbers, dry=False, fake_number=0):
    """Crée une issue (corps par l'entrée standard) et rend son numéro."""
    assignees = {"D": os.environ.get("DADDY_GH"), "M": os.environ.get("MANOA_GH")}
    title = f"[{issue['id']}] {issue['title']}"
    body = render_body(issue, numbers)
    cmd = ["issue", "create", "--title", title, "--body-file", "-", "--milestone", MILESTONES[issue["ms"]][0]]
    for lab in issue_labels(issue):
        cmd += ["--label", lab]
    for who in issue["owner"]:
        if assignees.get(who):
            cmd += ["--assignee", assignees[who]]
    if dry:
        print(f"  + {title}  [{MILESTONES[issue['ms']][0]}]")
        return fake_number
    url = gh(*cmd, input_text=body).strip()
    print(f"  + {url}  {title}")
    return int(url.rsplit("/", 1)[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--create", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.create):
        ap.error("préciser --dry-run ou --create")
    dry = args.dry_run

    ensure_labels(dry=dry)
    ensure_milestones(dry=dry)

    print(f"Issues ({len(ISSUES)})")
    existing = {} if dry else {k: v["number"] for k, v in existing_issues().items()}
    numbers = {}
    for n, issue in enumerate(ISSUES, start=1):
        if issue["id"] in existing:
            numbers[issue["id"]] = existing[issue["id"]]
            print(f"  = déjà présente : [{issue['id']}] {issue['title']}")
            continue
        numbers[issue["id"]] = create_issue(issue, numbers, dry=dry, fake_number=1000 + n)
    print("Terminé.")


if __name__ == "__main__":
    main()
