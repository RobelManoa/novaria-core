# Infrastructure AWS (Amazon Web Services) : cible documentée, non exécutée

> **Statut (20/10/2026).** Le projet s'exécute en local avec Docker Compose, d'après la consigne du professeur ([ADR-023](../docs/01-architecture/adr/ADR-023-execution-locale-d-abord.md)). Ce dossier est conservé : on y écrit et on y valide le code, **on n'exécute ni `plan` ni `apply`**, et aucun identifiant AWS n'est utilisé.

`terraform/modules` modules réutilisables · `terraform/envs/dev|demo` environnements · `ecs/` définitions de tâches ECS (Elastic Container Service).
Région : eu-west-1. Authentification GitHub → AWS par OIDC (OpenID Connect), sans clé d'accès longue durée.
Les fichiers d'état et `*.tfvars` ne sont jamais versionnés.

Contrôles possibles sans compte (à lancer depuis `infra/terraform/envs/<env>`) :

| Étape | Commande (identique sous Linux et Windows) |
|---|---|
| Format | `terraform fmt -check -recursive ../..` |
| Initialisation sans état distant | `terraform init -backend=false` |
| Validation | `terraform validate` |
| Lint | `tflint` |

Équivalents locaux de chaque service : [ADR-025](../docs/01-architecture/adr/ADR-025-equivalents-locaux-des-services-aws.md). Index des documents AWS : [docs/05-cloud-aws](../docs/05-cloud-aws/README.md).
