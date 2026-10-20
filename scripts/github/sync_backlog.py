#!/usr/bin/env python3
"""Met le backlog GitHub à jour avec la version 3 (20/10/2026) : issues nouvelles et amendements.

Ce script lit tout le backlog (issues_data, issues_suite, issues_microservices, issues_v3), retrouve chaque
issue sur GitHub par son identifiant `[ID]` (le titre peut donc changer) et n'agit que sur demande :

  --create          crée les issues absentes (les 13 nouvelles : LOC-01 à LOC-06, DAT-10, IA-08 à IA-11, GES-19, DOC-11)
  --amend           pour chaque issue amendée : ajoute les étiquettes et publie UN commentaire d'explication
                    (marqueur invisible : relancer le script ne le republie pas)
  --rewrite-bodies  réécrit le corps (tâches, critère, dépendances) et le titre des issues amendées,
                    SAUF si une case est déjà cochée (le travail en cours n'est jamais écrasé)
  --only ID[,ID]    limite l'action à ces identifiants
  --dry-run         n'écrit rien : affiche ce qui serait fait (lit GitHub en lecture seule ; --offline pour ne rien lire)

Ordre conseillé :
  Linux    python3 scripts/github/sync_backlog.py --dry-run
  Windows  py -3 scripts/github/sync_backlog.py --dry-run
  puis avec --create --amend, puis (après relecture des commentaires) avec --rewrite-bodies.

Prérequis : `gh auth login` effectué, dépôt courant relié à GitHub.
Variables facultatives : DADDY_GH et MANOA_GH (identifiants GitHub) pour assigner les nouvelles issues.
Ce script ne modifie ni la protection de branche, ni les paramètres du dépôt, ni les contrôles de la CI.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bootstrap  # noqa: E402  (configure aussi la sortie en UTF-8)
import issues_data  # noqa: E402
import issues_microservices  # noqa: E402,F401  (étend issues_data.ISSUES)
import issues_suite  # noqa: E402,F401  (étend issues_data.ISSUES)
import issues_v3  # noqa: E402

EXTRA_LABELS = [
    (issues_v3.DIFFERE, "9CA3AF", "Différée : exécution locale, AWS non utilisé (ADR-023)"),
    (issues_v3.REORIENTE, "0EA5E9", "Réorientée vers l'exécution locale (ADR-023)"),
    (issues_v3.MAJ, "A3E635", "Contenu mis à jour par le backlog v3 du 20/10/2026"),
]
BODY_KEYS = ("replace", "add", "drop", "title", "done", "proof", "deps_add", "deps_remove")
CHECKED = re.compile(r"- \[[xX]\]")


def marker(issue_id):
    return f"<!-- novaria-amend:v3:{issue_id} -->"


def comment_text(issue_id, note):
    return (f"{marker(issue_id)}\n**Mise à jour du backlog du 20/10/2026**\n\n{note}\n\n"
            "<sub>Décisions : ADR-023 à ADR-028 (`docs/01-architecture/adr/`).</sub>")


def selected(ids, only):
    return [i for i in ids if not only or i in only]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", action="store_true", help="avec --dry-run : ne lit pas GitHub")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--amend", action="store_true")
    ap.add_argument("--rewrite-bodies", action="store_true")
    ap.add_argument("--only", default="", help="identifiants séparés par des virgules")
    args = ap.parse_args()

    actions = {k for k in ("create", "amend", "rewrite_bodies") if getattr(args, k)}
    if not actions and not args.dry_run:
        ap.error("préciser --dry-run, ou au moins une action : --create, --amend, --rewrite-bodies")
    if args.offline and not args.dry_run:
        ap.error("--offline ne s'utilise qu'avec --dry-run")
    if args.dry_run and not actions:
        actions = {"create", "amend", "rewrite_bodies"}
    dry = args.dry_run
    only = {x.strip() for x in args.only.split(",") if x.strip()}

    issues = issues_data.ISSUES
    unknown = only - {i["id"] for i in issues}
    if unknown:
        ap.error("identifiants inconnus : " + ", ".join(sorted(unknown)))
    amended_ids = issues_v3.apply_amendments(issues)  # en mémoire seulement
    by_id = {i["id"]: i for i in issues}
    print(f"Backlog : {len(issues)} issues, dont {len(issues_v3.NEW_IDS)} nouvelles et {len(amended_ids)} amendées.")

    # --- état actuel de GitHub
    if dry and args.offline:
        existing = {}
        print("Mode hors ligne : GitHub n'est pas lu, toutes les issues sont supposées absentes.")
    else:
        existing = bootstrap.existing_issues()
        print(f"GitHub : {len(existing)} issues repérées par identifiant.")
    numbers = {k: v["number"] for k, v in existing.items()}

    # --- 1. création
    created = set()
    if "create" in actions:
        missing = selected([i["id"] for i in issues if i["id"] not in existing], only)
        print(f"\nCréation : {len(missing)} issue(s) absente(s) de GitHub")
        if missing:
            bootstrap.ensure_labels(EXTRA_LABELS, dry=dry)
            bootstrap.ensure_milestones(dry=dry)
        for n, issue_id in enumerate(missing, start=1):
            numbers[issue_id] = bootstrap.create_issue(by_id[issue_id], numbers, dry=dry, fake_number=2000 + n)
            created.add(issue_id)
    elif "amend" in actions and not dry:
        bootstrap.ensure_labels(EXTRA_LABELS, dry=False)

    # --- 2. commentaires et étiquettes
    if "amend" in actions:
        ids = selected(sorted(amended_ids), only)
        print(f"\nAmendements : {len(ids)} issue(s) amendée(s)")
        for issue_id in ids:
            change = issues_v3.AMENDMENTS[issue_id]
            if issue_id in created:
                print(f"  = {issue_id} : créée à l'instant avec le contenu amendé, pas de commentaire")
                continue
            if issue_id not in numbers:
                print(f"  ! {issue_id} : absente de GitHub (lancer d'abord --create)")
                continue
            number = numbers[issue_id]
            labels = ",".join(change.get("labels", []))
            if dry and args.offline:
                already = False
            else:
                raw = bootstrap.gh("issue", "view", str(number), "--json", "comments")
                already = any(marker(issue_id) in (c.get("body") or "") for c in json.loads(raw)["comments"])
            if already:
                print(f"  = #{number} {issue_id} : commentaire déjà publié")
                continue
            print(f"  + #{number} {issue_id} : étiquettes [{labels}] + commentaire")
            if not dry:
                if labels:
                    bootstrap.gh("issue", "edit", str(number), "--add-label", labels)
                bootstrap.gh("issue", "comment", str(number), "--body-file", "-",
                             input_text=comment_text(issue_id, change["note"]))

    # --- 3. réécriture des corps
    if "rewrite_bodies" in actions:
        ids = [i for i in selected(sorted(amended_ids), only) if any(k in issues_v3.AMENDMENTS[i] for k in BODY_KEYS)]
        print(f"\nRéécriture des corps : {len(ids)} issue(s) concernée(s)")
        for issue_id in ids:
            if issue_id in created:
                continue
            if issue_id not in existing:
                print(f"  ! {issue_id} : absente de GitHub")
                continue
            current = existing[issue_id]
            issue = by_id[issue_id]
            new_body = bootstrap.render_body(issue, numbers)
            new_title = f"[{issue_id}] {issue['title']}"
            if CHECKED.search(current["body"]):
                print(f"  - #{current['number']} {issue_id} : une case est cochée, corps conservé (voir le commentaire)")
                continue
            if new_body.strip() == current["body"].strip() and new_title == current["title"]:
                print(f"  = #{current['number']} {issue_id} : déjà à jour")
                continue
            print(f"  ~ #{current['number']} {issue_id} : corps et titre réécrits")
            if not dry:
                bootstrap.gh("issue", "edit", str(current["number"]), "--title", new_title, "--body-file", "-",
                             input_text=new_body)
    print("\nTerminé." + (" (essai : rien n'a été écrit)" if dry else ""))


if __name__ == "__main__":
    main()
