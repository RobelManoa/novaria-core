# Infrastructure AWS

`terraform/modules` modules réutilisables · `terraform/envs/dev|demo` environnements · `ecs/` définitions de tâches ECS.
Région : eu-west-1. Authentification GitHub → AWS par OIDC (OpenID Connect), sans clé d'accès longue durée.
Les fichiers d'état et `*.tfvars` ne sont jamais versionnés.
