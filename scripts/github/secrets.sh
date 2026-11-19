#!/usr/bin/env bash
# Enregistre les secrets et variables de GitHub Actions. Les valeurs ne sont jamais écrites dans l'historique du shell.
#   bash scripts/github/secrets.sh       -> SONAR_TOKEN et SNYK_TOKEN (à faire maintenant)
#   bash scripts/github/secrets.sh aws   -> variables AWS : REFUSÉ sans l'accord écrit des deux membres (voir plus bas)
set -euo pipefail

if [ "${1:-}" = "aws" ]; then
  # Garde-fou : ces variables activent deploy.yml et terraform.yml, donc des ressources AWS payantes. Le projet s'exécute en local (ADR-023) et
  # CLAUDE.md (point 6) l'interdit sans accord écrit des deux membres : il faut le dire explicitement, une réponse distraite ne suffit pas.
  if [ "${NOVARIA_AWS_AUTORISE:-}" != "accord-ecrit-des-deux-membres" ]; then
    echo "Refusé : enregistrer les variables AWS active deploy.yml et terraform.yml (ressources AWS payantes)." >&2
    echo "Le projet s'exécute en local (ADR-023) ; il faut l'accord écrit des deux membres (CLAUDE.md, point 6)." >&2
    echo "Avec cet accord seulement : NOVARIA_AWS_AUTORISE=accord-ecrit-des-deux-membres bash scripts/github/secrets.sh aws" >&2
    exit 1
  fi
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
  echo "Variables AWS enregistrées : deploy.yml et terraform.yml s'activent."
  exit 0
fi

echo "Pour chaque secret, gh affiche « Paste your secret » : coller la valeur puis Entrée (rien ne s'affiche, c'est normal)."
for name in SONAR_TOKEN SNYK_TOKEN; do
  echo "--> $name"
  gh secret set "$name"
done
echo
echo "Terminé. Vérifier avec : gh secret list   (doit lister SONAR_TOKEN et SNYK_TOKEN)"
echo "Étape suivante : pousser une branche, ouvrir une pull request, regarder l'onglet Actions."
echo "Les workflows deploy.yml et terraform.yml restent inactifs tant que la variable AWS_ROLE_ARN n'existe pas."
