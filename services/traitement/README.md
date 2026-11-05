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
| Tests et couverture (échoue sous 70 %) | `pytest` (écrit `coverage.xml`) | `pytest` |
| Tests d'intégration en conteneur (PostgreSQL + MongoDB jetables) et rapport de couverture | `python3 scripts/dev/dev.py test-integration` | `py -3 scripts/dev/dev.py test-integration` |
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

## Tests, intégration en conteneur et couverture (BE-07)

Trois niveaux : unitaires et contrat (sans base, c'est ce que la CI exécute), intégration PostgreSQL, intégration MongoDB. Les tests d'intégration sont ignorés sans base ; `dev.py test-integration` monte PostgreSQL et MongoDB dans un projet Compose jetable, lance toute la suite avec le rapport de couverture (branches comprises) puis supprime le projet. Barrière : `pytest` échoue sous 70 % de couverture (`[tool.coverage.report]` de `pyproject.toml`).
Détail, rapport de couverture et limites : [tests et couverture](../../docs/04-devsecops/tests-et-couverture.md).

## Traitement en flux (MS-09)

Le même code et la même image portent un second processus : `python -m app.flux` (service Compose `traitement-flux`). Il lit `iot.raw`, nettoie, agrège par fenêtres de 1 et 5 minutes en temps d'événement, calcule l'état de congestion stabilisé, publie `traffic.indicators` et `errors.dlq`, et ouvre ou ferme les épisodes de `dwh.fact_congestion_episode`. Le cœur (`app/flux/`) ne dépend ni de Kafka ni des bases ; les adaptateurs sont dans `app/flux/adapters/`. Tout est décrit, avec les valeurs et les limites, dans [le document du flux](../../docs/03-donnees/flux.md).

| Besoin | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Tests unitaires du flux (sans base) | `python3 -m pytest tests/unit/flux` | `py -3 -m pytest tests/unit/flux` |
| Tests du flux contre Kafka, PostgreSQL et MongoDB réels | `python3 scripts/dev/dev.py test-integration --service flux` (ou `make test-integration-flux`) | `py -3 scripts/dev/dev.py test-integration --service flux` |
| Journaux du flux | `docker compose logs -f traitement-flux` | `docker compose logs -f traitement-flux` |

## Entrepôt, API de lecture et recommandations (MS-10)

Un troisième processus de la même image écrit l'entrepôt : `python -m app.pipeline` (service Compose `traitement-pipeline`). Il lit `traffic.indicators`, enregistre l'exécution dans `dwh.dim_run`, écrit `dwh.fact_traffic_window` (idempotent) et publie `traffic.recommendations` (formule de Webster). **L'écriture et la lecture sont séparées** : les services d'écriture (`traitement-flux`, `traitement-pipeline`) utilisent le compte `svc_traitement` ; l'API de ce service lit avec `svc_lecture`, qui n'a que le droit de lire. Tout est décrit, avec la preuve que l'API sert exactement un recalcul SQL de référence, dans [le document de l'entrepôt](../../docs/03-donnees/entrepot.md).

| Besoin | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Tests unitaires du pipeline (sans base) | `python3 -m pytest tests/unit/pipeline` | `py -3 -m pytest tests/unit/pipeline` |
| API contre recalcul SQL (PostgreSQL jetable) | `python3 scripts/dev/dev.py test-integration -- tests/integration/test_pipeline_recalcul_postgres.py` | `py -3 scripts/dev/dev.py test-integration -- tests/integration/test_pipeline_recalcul_postgres.py` |
| Journaux du pipeline | `docker compose logs -f traitement-pipeline` | `docker compose logs -f traitement-pipeline` |

## Journal d'audit et compteurs d'usage (BE-05)

Chaque appel authentifié (et chaque tentative de connexion) laisse une entrée dans la collection MongoDB `audit_logs` : qui (identifiant du compte), quoi (méthode et modèle de route), quand, résultat, `correlation_id`. Chaque appel est compté par point d'accès et par heure dans `usage_stats`. Aucun secret, corps de requête, en-tête, adresse IP ni nom d'utilisateur n'est écrit. L'écriture est au mieux : MongoDB arrêté ne change aucune réponse. La variable `AUDIT_MONGO_URL` (compte `svc_backend`, déjà fournie par Compose) l'active ; sans elle, rien n'est écrit.
Règles et limites : [journalisation d'audit](../../docs/02-specifications/journalisation-audit.md). Preuve : [capture MongoDB](../../docs/03-donnees/preuve-be05-audit-mongodb.md) et `tests/contract/test_audit_contract.py`.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Tests contre MongoDB | `NOVARIA_TEST_MONGO_URL=mongodb://svc_backend:…@127.0.0.1:27017/novaria?authSource=novaria pytest tests/integration/test_audit_mongo.py` | `$env:NOVARIA_TEST_MONGO_URL="…"; pytest tests/integration/test_audit_mongo.py` |

## Erreurs, validation et versionnement (BE-06)

Toute erreur a le même corps `application/problem+json` (schéma `Problem` de `contracts/openapi/common.yaml`) : erreurs levées par le code, validation Pydantic (champ fautif désigné, messages en français, valeur jamais reprise), route inconnue (404), méthode non permise (405, avec `Allow`), base injoignable (503) et **toute erreur imprévue** (500, sans détail technique, avec `correlation_id`). L'API est sous `/api/v1` ; `/api/v2` répond 404 en disant quelles versions existent.
Règles, catalogue des codes et limites : [erreurs, validation et versionnement](../../docs/02-specifications/erreurs-et-versions-api.md). Preuve : `tests/contract/test_errors_contract.py` (chaque erreur documentée dans le contrat est provoquée et vérifiée), `test_validation_contract.py`, `test_versioning_contract.py`.

Déclarer les erreurs d'une nouvelle route : `responses=errors(401, 403, 422, "5XX")` (`app/api/responses.py`), les mêmes codes que le contrat ; le test de contrat échoue sinon, et aussi si l'erreur n'a pas de test.

## Sécurité applicative (BE-08)

| Mécanisme | Réglage (`.env`, aucun n'est un secret) | Par défaut |
|---|---|---|
| CORS restreint : origines exactes, `GET` et `POST`, pas de cookies | `CORS_ALLOWED_ORIGINS` (jamais `*`) | Vide : aucune origine |
| En-têtes de sécurité sur toutes les réponses (`nosniff`, `X-Frame-Options`, `Referrer-Policy`, politique de contenu) | | |
| Limitation de la connexion : `429` avec `Retry-After` | `LOGIN_ATTEMPTS_PER_MINUTE`, `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_S` | 10 par minute et par adresse ; 5 échecs sur 15 minutes par identifiant |
| Adresse du client derrière la passerelle | `TRUSTED_PROXY_HOPS` | 0 (Compose met 1) |

Les secrets (`JWT_SECRET`, adresses des bases) ne viennent que de l'environnement : `.env` créé par `dev.py init-env`, jamais versionné ; la valeur d'exemple est refusée hors de l'environnement local ; aucun secret dans les journaux (le code n'en écrit pas, et un filet masque ce qui échapperait).
Règles, limites, correspondance avec AWS Secrets Manager et preuves : [sécurité applicative](../../docs/04-devsecops/securite-applicative.md).

Ajouter une route avec une autre méthode que `GET` ou `POST` : ajouter la méthode à `ALLOWED_METHODS` de `app/core/cors.py` (un test échoue sinon).

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
