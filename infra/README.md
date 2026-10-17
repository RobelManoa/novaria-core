# Infrastructure AWS

`terraform/modules` modules réutilisables · `terraform/envs/dev|demo` environnements · `ecs/` définitions de tâches ECS.
Région : eu-west-1. Authentification GitHub → AWS par OIDC (OpenID Connect), sans clé d'accès longue durée.
Les fichiers d'état et `*.tfvars` ne sont jamais versionnés.

## Déploiement automatique vers dev (CLD-12)

Le workflow `.github/workflows/deploy.yml` s'exécute après chaque CI verte sur `main` : il publie les images dans ECR (Elastic Container Registry) avec la révision comme étiquette, déploie `infra/ecs/taskdef-backend.json` et `taskdef-frontend.json`, puis compare la révision renvoyée par `/api/v1/health` au commit déployé. Le déploiement échoue si les deux diffèrent.

Il reste inactif tant que la variable `AWS_ROLE_ARN` n'existe pas.

### Avant de l'activer

1. Créer l'infrastructure (CLD-11) : dépôts ECR `novaria-backend` et `novaria-frontend`, cluster et services ECS, groupes de journaux `/novaria/dev/backend` et `/novaria/dev/frontend`, rôle OIDC pour GitHub.
2. Remplacer `REMPLACER_COMPTE_AWS` par l'identifiant du compte dans les deux fichiers `taskdef-*.json`.
3. Créer les trois paramètres SSM (Systems Manager) lus par le backend : `/novaria/dev/postgres-url`, `/novaria/dev/mongo-url`, `/novaria/dev/jwt-secret`.
4. Créer les rôles `novaria-dev-ecs-execution` (lecture des paramètres, ECR, journaux) et `novaria-dev-backend-task`, ou ajuster leurs noms dans les fichiers.
5. Définir les variables du dépôt (ou de l'environnement `dev`) : `AWS_ROLE_ARN`, `AWS_REGION`, `ECS_CLUSTER`, `ECS_SERVICE_BACKEND`, `ECS_SERVICE_FRONTEND`, `API_URL`.

### Points de conception

- La révision vient de l'image : `deploy.yml` construit avec `--build-arg GIT_SHA=<commit>`, le Dockerfile l'écrit dans la variable `GIT_SHA`, l'API la renvoie. Ne définissez pas `GIT_SHA` dans les définitions de tâche.
- `nginx.conf` envoie `/api/` vers l'hôte `backend:8000`. Sur ECS, le service frontend doit donc utiliser ECS Service Connect avec l'alias `backend` (les ports sont nommés dans les définitions de tâche pour cela), sinon nginx ne démarre pas.
