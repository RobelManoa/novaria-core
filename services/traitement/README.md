# Service Traitement (Python + FastAPI)

Cœur du flux de données : nettoie, agrège par fenêtres, alimente l'entrepôt `dwh`, publie indicateurs et
recommandations, sert l'API de lecture ([ADR-008](../../docs/01-architecture/adr/ADR-008-microservices.md)).
État : squelette issu de l'ancien dossier `backend/` (issue MS-04), qui porte les parties communes du
[gabarit](../_gabarit/README.md) : sonde `/api/v1/health`, configuration, journaux JSON avec identifiant de
corrélation, image non-root.

## Commandes

Depuis ce dossier.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Environnement | `python3 -m venv .venv && . .venv/bin/activate` | `py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1` |
| Dépendances | `pip install -r requirements-dev.txt` | `pip install -r requirements-dev.txt` |
| Lancer | `uvicorn app.main:app --reload` (http://localhost:8000/docs) | `uvicorn app.main:app --reload` |
| Tests et couverture | `pytest` (écrit `coverage.xml`) | `pytest` |
| Lint | `ruff check . && ruff format --check .` | `ruff check .; ruff format --check .` |

## Indicateurs lus depuis l'entrepôt (BE-04)

`GET /api/v1/indicators` (filtres de période et de zone, pagination par curseur), `GET /api/v1/indicators/{indicator_id}` et `GET /api/v1/indicators/latest`, en lecture seule sur la vue `dwh.v_indicator` avec la variable `POSTGRES_URL` (déjà fournie par Compose). Une exécution doit être enregistrée dans `dwh.dim_run` pour être servie. Détail : [API des indicateurs](../../docs/03-donnees/api-indicateurs.md). Preuve : `tests/contract/test_indicators_contract.py`.

## Authentification et rôles (BE-03)

Ce service porte aussi le rôle « API métier » : `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `GET` et `POST /api/v1/users`, `GET /api/v1/users/{user_id}`. Jetons JWT signés HS256 (secret `JWT_SECRET`, 32 caractères au moins), mots de passe en argon2id, trois rôles hiérarchiques. Sans jeton : 401 ; rôle insuffisant : 403.
Détail, parcours, codes d'erreur et limites : [authentification](../../docs/02-specifications/authentification.md). Le contrat de ces routes est `contracts/openapi/api-metier.openapi.yaml` (second contrat déclaré dans `pyproject.toml`).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Premier administrateur (mot de passe saisi sans écho) | `python3 scripts/dev/dev.py user-create alice --role admin` | `py -3 scripts/dev/dev.py user-create alice --role admin` |
| Tests sans base (comme la CI) | `pytest` | `pytest` |
| Tests contre PostgreSQL | `NOVARIA_TEST_POSTGRES_ADMIN_URL=postgresql+psycopg://novaria_admin:…@127.0.0.1:5432/novaria pytest` | `$env:NOVARIA_TEST_POSTGRES_ADMIN_URL="…"; pytest` |

Protéger une nouvelle route : `Depends(require_role(Role.OPERATOR))` et `openapi_extra={"x-required-role": "operator"}` ; le test de contrat échoue si la route n'est pas protégée ou si le rôle diffère du contrat.

## Migrations du schéma `app` (BE-02)

Le schéma `app` (utilisateurs, rôles) appartient à l'API métier : ses tables sont décrites par des modèles SQLAlchemy (`app/models/`) et créées par **Alembic** (`migrations/`), pas par `db/postgres/migrations/` ([ADR-024](../../docs/01-architecture/adr/ADR-024-bases-de-donnees-locales.md)). Le compte est `svc_app` ; l'adresse de la base est dans la variable `APP_DATABASE_URL`, jamais dans un fichier.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Créer le schéma sur la base locale (depuis la racine du dépôt) | `python3 scripts/dev/dev.py db-migrate-app` | `py -3 scripts/dev/dev.py db-migrate-app` |
| À la main (depuis ce dossier) | `APP_DATABASE_URL=postgresql+psycopg://svc_app:…@127.0.0.1:5432/novaria python -m alembic upgrade head` | `$env:APP_DATABASE_URL="postgresql+psycopg://svc_app:…@127.0.0.1:5432/novaria"; python -m alembic upgrade head` |
| Voir le SQL sans se connecter | `python -m alembic upgrade head --sql` | `python -m alembic upgrade head --sql` |
| Revenir à zéro | `python -m alembic downgrade base` | `python -m alembic downgrade base` |
| Tests contre un vrai PostgreSQL | `NOVARIA_TEST_POSTGRES_ADMIN_URL=postgresql+psycopg://novaria_admin:…@127.0.0.1:5432/novaria pytest tests/integration` | `$env:NOVARIA_TEST_POSTGRES_ADMIN_URL="…"; pytest tests/integration` |

Ajouter une table : modèle dans `app/models/`, puis `python -m alembic revision --autogenerate --rev-id 0002 -m "description"`, relire le fichier produit, ajouter les colonnes au dictionnaire de données (section 11.2 : un test échoue sinon). Une révision déjà appliquée ne se réécrit jamais.

Le dossier de preuve annoncé par l'issue BE-02 était `backend/migrations/` ; depuis MS-04 le service s'appelle `traitement` et les migrations sont ici, dans `migrations/`.

## Organisation

`api/` (routes) → `services/` (règles métier) → `repositories/` (accès PostgreSQL et MongoDB). Les
contrats d'interface sont décrits dans `contracts/openapi/traitement.openapi.yaml` (source de vérité).

## Points ouverts

| Point | Position actuelle |
|---|---|
| Le service Docker Compose s'appelle encore `backend`, et le compte de base reste `svc_app` | Renommage et comptes dédiés avec MS-06 et MS-10 |
| Les migrations Alembic ne sont pas dans l'image Docker (elle ne copie que `app/`) : elles se lancent depuis le poste (`db-migrate-app`) | À reprendre quand l'avenir du rôle « API métier » sera tranché |
| Avenir du rôle « API métier » (utilisateurs, jetons) : ce service ou un service à part | Point ouvert n° 1 des [diagrammes C4](../../docs/01-architecture/c4/README.md) |
