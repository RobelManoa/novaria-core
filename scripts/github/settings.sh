#!/usr/bin/env bash
# Configure le dépôt courant.
#   bash scripts/github/settings.sh           -> fusion, sécurité, environnements
#   bash scripts/github/settings.sh protect   -> protection de main (après la première CI verte)
# Prérequis : gh auth login ; être administrateur du dépôt ; dépôt public
# (la protection de branche n'est pas disponible gratuitement sur un dépôt privé).
set -euo pipefail

if [ "${1:-}" = "protect" ]; then
echo "Protection de la branche main"
gh api -X PUT repos/{owner}/{repo}/branches/main/protection --input - >/dev/null <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["backend", "frontend", "gitleaks", "snyk", "docker", "sonarqube"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
echo "Protection posée."
exit 0
fi

echo "1/3 Paramètres de fusion et fonctionnalités"
gh repo edit \
  --enable-issues --enable-projects \
  --enable-wiki=false \
  --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false \
  --delete-branch-on-merge --enable-auto-merge

gh api -X PATCH repos/{owner}/{repo} \
  -f squash_merge_commit_title=PR_TITLE \
  -f squash_merge_commit_message=PR_BODY >/dev/null

echo "2/3 Sécurité : alertes, correctifs automatiques, détection de secrets"
gh api -X PUT repos/{owner}/{repo}/vulnerability-alerts >/dev/null
gh api -X PUT repos/{owner}/{repo}/automated-security-fixes >/dev/null
gh api -X PATCH repos/{owner}/{repo} --input - >/dev/null <<'JSON'
{"security_and_analysis":{
  "secret_scanning":{"status":"enabled"},
  "secret_scanning_push_protection":{"status":"enabled"}}}
JSON

echo "3/3 Environnements"
gh api -X PUT repos/{owner}/{repo}/environments/dev >/dev/null
gh api -X PUT repos/{owner}/{repo}/environments/demo >/dev/null
echo "Terminé. À faire à la main : ajouter un relecteur obligatoire à l'environnement demo (Settings > Environments)."
