#!/usr/bin/env python3
"""Crée labels, jalons et issues du projet Novaria Core avec GitHub CLI (gh).

Usage :
  python scripts/github/bootstrap.py --dry-run          # affiche ce qui serait créé
  python scripts/github/bootstrap.py --create           # crée tout (idempotent : relançable)

Variables facultatives : DADDY_GH et MANOA_GH (identifiants GitHub) pour assigner les issues.
Prérequis : `gh auth login` effectué, dépôt courant relié à GitHub.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from issues_data import BC05, ISSUES, MILESTONES, PRIOS, TEAMS, TYPES  # noqa: E402

LEVEL = {"bigdata": "Prototype ciblé", "flux": "Prototype ciblé", "rpa": "Prototype ciblé"}
OWNERS = {"D": "Daddy Luciano", "M": "Manoa Robel", "DM": "Daddy Luciano et Manoa Robel (relecture croisée)"}


def gh(*args, dry=False, capture=True):
    if dry:
        print("  $ gh " + " ".join(args))
        return ""
    result = subprocess.run(["gh", *args], check=True, text=True, capture_output=capture)
    return result.stdout


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--create", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.create):
        ap.error("préciser --dry-run ou --create")
    dry = args.dry_run
    assignees = {"D": os.environ.get("DADDY_GH"), "M": os.environ.get("MANOA_GH")}

    print(f"Labels ({len(labels())})")
    for name, color, desc in labels():
        gh("label", "create", name, "--color", color, "--description", desc[:100], "--force", dry=dry)

    print(f"Jalons ({len(MILESTONES)})")
    existing_ms = set()
    if not dry:
        existing_ms = {m["title"] for m in json.loads(gh("api", "repos/{owner}/{repo}/milestones?state=all&per_page=100"))}
    for title, due, desc in MILESTONES:
        if title in existing_ms:
            continue
        gh("api", "repos/{owner}/{repo}/milestones", "-f", f"title={title}", "-f", f"due_on={due}T23:59:59Z",
           "-f", f"description={desc}", dry=dry)

    print(f"Issues ({len(ISSUES)})")
    existing = {}
    if not dry:
        for i in json.loads(gh("issue", "list", "--state", "all", "--limit", "1000", "--json", "number,title")):
            existing[i["title"]] = i["number"]
    numbers = {}
    for n, issue in enumerate(ISSUES, start=1):
        title = f"[{issue['id']}] {issue['title']}"
        if title in existing:
            numbers[issue["id"]] = existing[title]
            print(f"  = déjà présente : {title}")
            continue
        labels_ = [f"team:{issue['team']}", f"type:{issue['type']}", f"prio:{issue['prio']}", *[f"bc05:{k}" for k in issue["bc05"]]]
        cmd = ["issue", "create", "--title", title, "--body", render_body(issue, numbers),
               "--milestone", MILESTONES[issue["ms"]][0]]
        for lab in labels_:
            cmd += ["--label", lab]
        for who in issue["owner"]:
            if assignees.get(who):
                cmd += ["--assignee", assignees[who]]
        if dry:
            print(f"  + {title}  [{MILESTONES[issue['ms']][0]}]")
            numbers[issue["id"]] = 1000 + n
        else:
            url = gh(*cmd).strip()
            numbers[issue["id"]] = int(url.rsplit("/", 1)[1])
            print(f"  + {url}  {title}")
    print("Terminé.")


if __name__ == "__main__":
    main()
