# Contribuer

## Branches
- `main` est protégée : toute modification passe par une pull request approuvée par l'autre membre.
- Une branche par issue : `feature/<ID>-court-titre` (ex. `feature/BE-03-auth-jwt`), `fix/...`, `docs/...`.
- Branches courtes : fusion par squash, suppression automatique après fusion.

## Commits
Format : `type(portée): résumé` — types : `feat`, `fix`, `docs`, `test`, `chore`, `ci`, `refactor`.
Exemple : `feat(traitement): ajoute les fenêtres de 1 minute`.

## Pull request
1. Lier l'issue (`Closes #n`).
2. CI verte : backend (tous les services), frontend, gitleaks, snyk, docker, sonarqube.
3. Relecture croisée par l'autre membre ; conversations résolues.
4. Mettre à jour la documentation et le contrat OpenAPI si l'API change.

## Créer un nouveau service

Chaque service vit dans `services/<nom>/` et naît de `services/_gabarit/`, un vrai service qui passe lint, tests et construction de l'image. Il apporte déjà : la sonde `GET /api/v1/health`, la configuration par variables d'environnement, des journaux JSON avec identifiant de corrélation (`X-Correlation-ID`), des tests et une image non-root.

| Étape | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| 1. Créer la branche | `git switch -c feature/<ID>-<nom>` | `git switch -c feature/<ID>-<nom>` |
| 2. Créer le service | `python3 scripts/dev/dev.py new-service <nom>` (ou `make new-service N=<nom>`) | `py -3 scripts/dev/dev.py new-service <nom>` |
| 3. Préparer l'environnement | `cd services/<nom> && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt` | `cd services/<nom>; py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt` |
| 4. Vérifier | `ruff check . && ruff format --check . && pytest` | `ruff check .; ruff format --check .; pytest` |
| 5. Construire l'image | `docker build -t novaria-<nom> .` | `docker build -t novaria-<nom> .` |
| Ajouter une dépendance | éditer `requirements.in`, puis `python3 scripts/dev/dev.py lock-deps <nom>` | éditer `requirements.in`, puis `py -3 scripts/dev/dev.py lock-deps <nom>` |

Le nom : minuscules, chiffres et tirets, deux à trente et un caractères, commençant par une lettre (`alerte`, `reponse-exterieure`).

Les dépendances s'écrivent dans `requirements.in` ; `requirements.txt` est un **verrou généré** (versions exactes et empreintes) que l'image installe avec `--require-hashes --only-binary :all:` : voir [dependances-verrouillees.md](docs/04-devsecops/dependances-verrouillees.md).

**Il n'y a rien à modifier dans la CI** : son job `services` découvre les dossiers de `services/` et lance une exécution `service (<nom>)` par dossier (lint, tests, image), que le contrôle obligatoire `backend` rassemble ; ses jobs `snyk` et `docker` parcourent `services/*/`, et `sonar-project.properties` et `.github/dependabot.yml` couvrent `services/`. Détails : [docs/04-devsecops/ci-multi-services.md](docs/04-devsecops/ci-multi-services.md). Le test `scripts/dev/test_gabarit.py` échoue si un chemin de service est écrit en dur.

Ensuite, et selon l'issue :

1. Écrire les routes et la logique dans `app/` ; garder l'architecture décidée dans l'[ADR-008](docs/01-architecture/adr/ADR-008-microservices.md) et l'[ADR-010](docs/01-architecture/adr/ADR-010-architecture-hexagonale.md).
2. Écrire le contrat d'API et les schémas d'événements du service avant son code (`docs/02-specifications/`, `contracts/`).
3. Ajouter le service à `docker-compose.yml` (issue MS-06).
4. Un service ne partage pas de bibliothèque avec les autres : le code commun du gabarit se **copie**. Si le gabarit s'améliore, reporter le changement dans les services existants par une pull request dédiée.

## Secrets
Aucun secret dans le code, les captures ou les journaux. Variables locales dans `.env` (ignoré par Git), secrets CI dans GitHub Actions.

## Usage de l'IA
Chaque usage significatif est inscrit dans `docs/ia/journal-usage-ia.md` avec son but, son prompt et la vérification effectuée.
