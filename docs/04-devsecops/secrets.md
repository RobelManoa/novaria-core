# Inventaire des secrets

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 20/10/2026
Issue de suivi : GES-16

Ce document liste chaque jeton, mot de passe et clé du projet : à quoi il sert, où il est stocké, qui en répond, quand il expire et quand il est renouvelé. **Il ne contient aucune valeur**, jamais : seuls les noms figurent ici. Le dépôt est public.

Abréviations : 2FA (Two-Factor Authentication, authentification à deux facteurs), CI (Continuous Integration, intégration continue), OIDC (OpenID Connect), SSH (Secure Shell), SSM (Systems Manager).

## 1. Inventaire

### 1.1 Secrets de la CI (GitHub)

| N° | Nom | Usage | Lieu de stockage | Propriétaire | Dernière modification (UTC) | Expiration | Renouvellement |
|---|---|---|---|---|---|---|---|
| S1 | `SNYK_TOKEN` (Actions) | Contrôles Snyk des jobs `snyk` et `docker` de `ci.yml` | Secrets GitHub Actions du dépôt | Manoa Robel | 2026-10-16 20:25 | Mi-janvier 2027 [À COMPLÉTER : date exacte lue dans Snyk] | Voir section 5 |
| S2 | `SNYK_TOKEN` (Dependabot) | Mêmes contrôles sur les pull requests ouvertes par Dependabot, qui n'ont pas accès aux secrets Actions | Secrets Dependabot du dépôt | Manoa Robel | 2026-10-17 06:37 | Mi-janvier 2027 [À COMPLÉTER] | Voir section 5 |
| S3 | `SONAR_TOKEN` (Actions) | Analyse SonarQube Cloud du job `sonarqube` | Secrets GitHub Actions du dépôt | Manoa Robel | 2026-10-16 16:18 | [À COMPLÉTER : lire dans SonarQube Cloud, My Account, Security] | Voir section 5 |
| S4 | `SONAR_TOKEN` (Dependabot) | Même analyse pour les pull requests de Dependabot | Secrets Dependabot du dépôt | Manoa Robel | 2026-10-17 06:36 | [À COMPLÉTER] | Voir section 5 |
| S5 | `GITHUB_TOKEN` | Jeton automatique de chaque exécution de la CI, lecture du code (`contents: read`) | Créé par GitHub à chaque exécution, jamais stocké | GitHub | À chaque exécution | Fin de l'exécution | Aucun |

Les deux environnements GitHub (`dev`, `demo`) n'ont aucun secret ni aucune variable. Le dépôt n'a aucune variable : `deploy.yml` et `terraform.yml` restent inactifs (exécution locale, ADR-023).

### 1.2 Accès personnels de chaque membre

| N° | Nom | Usage | Lieu de stockage | Propriétaire | Expiration | Renouvellement |
|---|---|---|---|---|---|---|
| S6 | Jeton de la CLI `gh` | Commandes `gh` (pull requests, issues, secrets) | Trousseau du système du poste, jamais dans un fichier du dépôt | Chaque membre, pour son compte | Aucune connue [non vérifié] ; droits : `gist`, `read:org`, `repo`, `workflow` | À la demande : `gh auth refresh` ou nouvelle connexion |
| S7 | Clé SSH de GitHub | `git push` et `git pull` | Dossier SSH du poste ; la clé privée n'est jamais copiée ni partagée | Chaque membre | Aucune | À la demande, si le poste change ou si la clé est exposée |

### 1.3 Secrets locaux (`.env`)

Ces secrets sont créés par `dev.py init-env` (valeurs aléatoires, fichier en lecture réservée au propriétaire, ignoré par Git). Chaque membre a son propre `.env`, avec ses propres valeurs : aucune valeur n'est partagée entre les postes.

| N° | Nom | Usage | Propriétaire |
|---|---|---|---|
| L1 | `POSTGRES_PASSWORD` | Administrateur PostgreSQL | Chaque membre |
| L2 | `PG_PASSWORD_APP` | Rôle de l'API métier (schéma `app`) | Chaque membre |
| L3 | `PG_PASSWORD_TRAITEMENT` | Rôle du service de traitement (schéma `dwh`) | Chaque membre |
| L4 | `PG_PASSWORD_ALERTE` | Rôle du service d'alerte (schéma `alertes`) | Chaque membre |
| L5 | `PG_PASSWORD_LECTURE` | Rôle en lecture seule de l'entrepôt | Chaque membre |
| L6 | `MONGO_ROOT_PASSWORD` | Administrateur MongoDB | Chaque membre |
| L7 | `MONGO_PASSWORD_COLLECTE` | Rôle du service de collecte | Chaque membre |
| L8 | `MONGO_PASSWORD_TRAITEMENT` | Rôle du service de traitement | Chaque membre |
| L9 | `MONGO_PASSWORD_REPONSE` | Rôle du service de réponse extérieure | Chaque membre |
| L10 | `MONGO_PASSWORD_BACKEND` | Rôle du back-end | Chaque membre |
| L11 | `MONGO_PASSWORD_ML` | Rôle du service de machine learning | Chaque membre |
| L12 | `JWT_SECRET` | Signature des jetons d'authentification du back-end (prévu pour l'issue BE-03) | Chaque membre |

| Élément commun à L1 à L12 | Valeur |
|---|---|
| Lieu de stockage | Fichier `.env` à la racine du dépôt de chaque poste |
| Expiration | Aucune |
| Renouvellement | À la demande (fuite, changement de poste) : `init-env --force`, puis `db-reset`, qui **efface les données locales** (les mots de passe des bases déjà créées ne changent pas sans cela) |

### 1.4 Différés (aucune ressource AWS)

| Élément | Raison |
|---|---|
| Rôle OIDC GitHub vers AWS (variable `AWS_ROLE_ARN`) | Aucun compte AWS : exécution locale d'abord (C-05, ADR-023) |
| Paramètres SSM `/novaria/dev/postgres-url`, `/mongo-url`, `/jwt-secret` | Référencés par `infra/ecs/taskdef-backend.json`, non créés |

## 2. Contrôle d'exposition du 20/10/2026

| Vérification | Résultat |
|---|---|
| Recherche de secrets par gitleaks dans tout l'historique (`--log-opts=--all`, 52 commits) | Aucune fuite |
| gitleaks sur les fichiers du dossier de travail | 12 détections, **toutes dans `.env`** : ce sont les 12 mots de passe locaux de la section 1.3, fichier ignoré par Git (attendu) |
| Fichiers sensibles suivis par Git (`.env`, `backups/`, clés) | Aucun : seul `.env.example` est suivi, sans valeur réelle |
| Identifiants de forme UUID (format d'un jeton Snyk) dans tous les commits | Seulement des identifiants d'événements d'exemple dans `contracts/events/examples/` |
| Captures d'écran suivies (`docs/Capture d'ecran/`, 2 fichiers) | Aucun jeton visible |
| Secrets GitHub et Dependabot | Seulement `SNYK_TOKEN` et `SONAR_TOKEN`, chacun aux deux endroits ; aucun secret d'environnement |
| Protections GitHub | Détection de secrets (secret scanning) et protection au push : activées |
| Fichier `.env.ancien` (anciens mots de passe locaux) | Supprimé |
| Conversation avec un assistant IA et terminal | **Un jeton Snyk a été exposé le 16/10/2026** (affiché dans un terminal et collé dans une conversation). Aucune valeur n'est dans le dépôt. À révoquer : section 3 |

## 3. Jeton exposé : révocation

| Étape | Qui | État |
|---|---|---|
| Révoquer le jeton Snyk exposé et en générer un nouveau (Snyk : Account settings, General, Auth Token, « Revoke & regenerate ») | Manoa Robel | [À CONFIRMER : date] |
| Enregistrer le nouveau jeton dans S1 et S2 sans l'afficher : `gh secret set SNYK_TOKEN`, puis `gh secret set SNYK_TOKEN --app dependabot` | Manoa Robel | [À CONFIRMER] |
| Vérifier que l'ancien jeton est refusé (réponse 401) | Manoa Robel | [À CONFIRMER] |

Vérification : la commande demande le jeton sans l'afficher, puis n'écrit que le code de réponse.

| Linux (bash) | Windows (PowerShell) |
|---|---|
| `read -rs T; curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: token $T" https://api.snyk.io/v1/user/me; unset T` | `$s = Read-Host "Jeton" -AsSecureString; $T = [System.Net.NetworkCredential]::new("", $s).Password; curl.exe -s -o NUL -w "%{http_code}" -H "Authorization: token $T" https://api.snyk.io/v1/user/me; Remove-Variable T` |

Réponse **401** : le jeton est révoqué. Réponse 200 : il est encore valide, il faut le révoquer.

## 4. Authentification à deux facteurs

| Service | Membre | État | Preuve |
|---|---|---|---|
| GitHub | Manoa Robel | [À CONFIRMER] | [À COMPLÉTER : paramètres du compte, sans capture de code] |
| GitHub | Daddy Luciano | [À CONFIRMER] | [À COMPLÉTER] |
| Snyk | Manoa Robel | [À CONFIRMER] | [À COMPLÉTER] |
| SonarQube Cloud | Manoa Robel | [À CONFIRMER] | [À COMPLÉTER] |
| AWS | Les deux | Sans objet : aucun compte AWS (ADR-023) | À activer à l'ouverture du compte (CLD-01) |

Le critère de l'issue (« la double authentification est active partout ») n'est **pas vérifié** : l'état de chaque compte se contrôle dans l'interface du service, hors de portée de ce dépôt. Aucune capture ne doit montrer un code, une clé de secours ou un code QR.

## 5. Renouvellement

| Date | Action |
|---|---|
| Avant chaque jalon (M1 à M6) | Relire cet inventaire : un nouveau secret a-t-il été ajouté sans ligne ici ? |
| 10/12/2026 | Soutenance |
| 11/12/2026 (proposition) | Révoquer S1 à S4 (Snyk et SonarQube Cloud) puisque le projet est terminé, ou les renouveler si le projet continue |
| Mi-janvier 2027 | Expiration du jeton Snyk : renouvelé ou déjà révoqué à cette date |

Procédure de renouvellement d'un secret de CI : générer le nouveau jeton dans le service, l'enregistrer avec `gh secret set NOM` (et `--app dependabot` pour la copie de Dependabot), relancer la CI, puis révoquer l'ancien jeton.

## 6. Règles

- Une valeur n'est jamais écrite dans un fichier du dépôt, une capture, un message de commit, une issue, un journal ou une conversation (y compris avec un assistant IA).
- Un secret se saisit dans un champ masqué (`gh secret set NOM`, `read -rs`) ou depuis le presse-papiers, jamais en argument d'une commande.
- Un secret exposé est révoqué immédiatement, puis remplacé et consigné dans ce document ; il n'est pas « nettoyé » seulement dans la conversation ou l'historique.
- Tout nouveau secret reçoit une ligne ici (usage, lieu, propriétaire, expiration, renouvellement) avant d'être utilisé.

## 7. Contrôle automatique

Le test `scripts/dev/test_secrets.py` vérifie que chaque secret de la CI (`secrets.NOM` dans `.github/workflows/`) et chaque secret local de `.env.example` figure dans cet inventaire, que chaque ligne a un propriétaire, et que le document ne contient aucune valeur de forme jeton.

| Linux (bash) | Windows (PowerShell) |
|---|---|
| `python3 -m unittest discover -s scripts/dev` | `py -3 -m unittest discover -s scripts/dev` |
