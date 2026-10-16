# Contribuer

## Branches
- `main` est protégée : toute modification passe par une pull request approuvée par l'autre membre.
- Une branche par issue : `feature/<ID>-court-titre` (ex. `feature/BE-03-auth-jwt`), `fix/...`, `docs/...`.
- Branches courtes : fusion par squash, suppression automatique après fusion.

## Commits
Format : `type(portée): résumé` — types : `feat`, `fix`, `docs`, `test`, `chore`, `ci`, `refactor`.
Exemple : `feat(backend): ajoute l'authentification JWT`.

## Pull request
1. Lier l'issue (`Closes #n`).
2. CI verte : backend, frontend, gitleaks, snyk, docker, sonarqube.
3. Relecture croisée par l'autre membre ; conversations résolues.
4. Mettre à jour la documentation et le contrat OpenAPI si l'API change.

## Secrets
Aucun secret dans le code, les captures ou les journaux. Variables locales dans `.env` (ignoré par Git), secrets CI dans GitHub Actions.

## Usage de l'IA
Chaque usage significatif est inscrit dans `docs/ia/journal-usage-ia.md` avec son but, son prompt et la vérification effectuée.
