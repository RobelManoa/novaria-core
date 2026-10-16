#!/usr/bin/env bash
# Enregistre secrets et variables d'Actions. Chaque valeur est demandée en saisie masquée (jamais dans l'historique).
set -euo pipefail

for name in SONAR_TOKEN SNYK_TOKEN; do
  gh secret set "$name"
done

read -rp "AWS_REGION (ex. eu-west-1) : " region
read -rp "AWS_ROLE_ARN (rôle OIDC GitHub) : " role
read -rp "ECS_CLUSTER : " cluster
read -rp "ECS_SERVICE_BACKEND : " sb
read -rp "ECS_SERVICE_FRONTEND : " sf
read -rp "API_URL (https://...) : " api

gh variable set AWS_REGION --body "$region"
gh variable set AWS_ROLE_ARN --body "$role"
gh variable set ECS_CLUSTER --body "$cluster"
gh variable set ECS_SERVICE_BACKEND --body "$sb"
gh variable set ECS_SERVICE_FRONTEND --body "$sf"
gh variable set API_URL --body "$api"
echo "Secrets et variables enregistrés."
