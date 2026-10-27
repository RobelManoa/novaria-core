# Démarrage : intégrer le projet en une heure

Ce guide s'adresse à toute personne qui rejoint Novaria Core, côté backend ou frontend. Il part d'un poste vierge et finit par une première pull request. Les règles complètes de contribution sont dans [CONTRIBUTING.md](../CONTRIBUTING.md).

## 1. Prérequis

| Outil | Version | Vérification |
|---|---|---|
| Git | récente | `git --version` |
| Docker et Docker Compose | récente | `docker info` (sans `sudo`) |
| Python | 3.12 (celle de la CI) | `python3 --version` |
| Node.js | 22 | `node --version` |
| Make | toute version | `make --version` |

Sous Linux, ajoutez-vous au groupe Docker : `sudo usermod -aG docker $USER`, puis rouvrez la session.

Il faut un compte GitHub avec accès au dépôt `RobelManoa/novaria-core`. Aucun jeton Snyk ou Sonar n'est nécessaire en local : ces secrets ne servent qu'à la CI.

## 2. Démarrer l'environnement

```bash
git clone git@github.com:RobelManoa/novaria-core.git
cd novaria-core
cp .env.example .env      # valeurs locales sans danger ; le fichier n'est jamais versionné
make up                   # tout : bases, bus, 4 services, simulateur, passerelle, front-end (puis vérifie chaque /health)
```

| Conteneur | Adresse sur le poste | Sonde de santé |
|---|---|---|
| Frontend | http://localhost:8080 | `/` |
| Passerelle (point d'entrée de l'API) | http://localhost:8000/api/v1/ | http://localhost:8000/health |
| Collecte, traitement, alerte, reponse | `127.0.0.1:8001`, `8002`, `8003`, `8004` | `/api/v1/health` de chacun |
| Simulateur | `127.0.0.1:8005` | `/api/v1/health` |
| PostgreSQL | `localhost:5432` | |
| MongoDB | `localhost:27017` | |
| Kafka (bus d'événements) | `127.0.0.1:9094` depuis le poste, `kafka:9092` depuis un conteneur ; sujets : `make kafka-topics` ([kafka-local.md](08-exploitation/kafka-local.md)) |

Le test est réussi quand `make up` finit par « Les 9 sondes répondent » (`make health` le refait à tout moment). Pour arrêter : `make down` (les données sont conservées). Pour suivre les journaux d'un service : `make logs S=traitement`. Ordre de démarrage, ports et dépannage : [pile-locale.md](08-exploitation/pile-locale.md).

**Port déjà utilisé** (erreur `address already in use`) : un PostgreSQL, un MongoDB ou un autre programme local occupe le port. Changez la variable correspondante dans votre `.env` (par exemple `POSTGRES_PORT=5433`, `MONGO_PORT=27018` ou `GATEWAY_PORT=8100` ; la liste est dans `.env.example`), puis relancez `make up`. Les conteneurs continuent de se parler sur les ports internes habituels.

Accès aux bases depuis le terminal :

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose exec mongo sh -c 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin'
```

## 3. Travailler côté backend

Le backend est une API FastAPI versionnée sous `/api/v1`. Organisation du dossier `services/traitement/app/` :

| Dossier | Rôle |
|---|---|
| `api/v1/` | Routes HTTP : valident l'entrée, appellent un service, renvoient un schéma |
| `services/` | Règles métier, sans accès direct à la base |
| `repositories/` | Accès à PostgreSQL et à MongoDB |
| `models/` | Modèles de base de données |
| `schemas/` | Schémas d'entrée et de sortie (Pydantic) |
| `core/` | Configuration lue depuis les variables d'environnement |
| `db/` | Connexions aux bases |

Le dossier `services/traitement/tests/` contient `unit/`, `integration/` et `contract/` (conformité au contrat OpenAPI). `services/traitement/migrations/` accueillera les migrations Alembic.

### Boucle de développement locale (avec rechargement automatique)

```bash
docker compose up -d postgres mongo     # les bases seulement
cd services/traitement
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload           # http://localhost:8000/docs
```

Les variables lues par le backend sont les mêmes que celles que `docker-compose.yml` injecte : `ENVIRONMENT`, `GIT_SHA`, `POSTGRES_URL`, `MONGO_URL`, `MONGO_DB`, `JWT_SECRET`. En local hors Docker, créez `services/traitement/.env` (ignoré par Git) avec les mêmes noms, en remplaçant `postgres` et `mongo` par `localhost` et en utilisant les ports hôte de votre `.env`.

### Vérifier avant chaque commit

```bash
cd services/traitement
ruff check . && ruff format --check .    # corrige avec : ruff check --fix . && ruff format .
python -m pytest                         # tests + couverture (coverage.xml)
```

`make lint`, `make test` et `make format` lancent le backend et le frontend ensemble. Ils exigent que l'environnement virtuel Python soit activé.

### Ajouter un endpoint, pas à pas

1. Décrire la route dans le contrat de son service, dans `contracts/openapi/` (source de vérité : `<nom du service>.openapi.yaml`).
2. Écrire le test d'abord dans `services/traitement/tests/` (modèle : `tests/unit/test_health.py`).
3. Créer le schéma dans `schemas/`, la logique dans `services/`, l'accès aux données dans `repositories/`.
4. Brancher la route dans `api/v1/` et l'inclure dans `app/main.py`.
5. Lancer `ruff` et `pytest`, puis ouvrir la pull request.

### Dépendances à ajouter

`requirements.txt` ne contient pour l'instant que FastAPI, Uvicorn et Pydantic. Les issues à venir demandent d'ajouter, au moment voulu : SQLAlchemy et Alembic (BE-02), un pilote PostgreSQL (le compose utilise `postgresql+psycopg://`), un client MongoDB, et une bibliothèque JWT (BE-03). Ajoutez-les avec une borne de version, comme les lignes existantes.

## 4. Travailler côté frontend

```bash
cd frontend
npm ci                    # installe exactement le package-lock.json
npm run dev               # http://localhost:5173, les appels /api passent par le proxy vers le port 8000
npm test                  # vitest + couverture
npm run lint && npm run format:check
npm run build             # contrôle de types puis construction
```

Le code est dans `frontend/src/` : `app/`, `components/`, `features/`, `hooks/`, `pages/`, `services/` (client d'API), `styles/`, `types/`. Le formatage est géré par Prettier : `npx prettier --write src`. Le backend doit tourner pour que le proxy `/api` réponde.

## 5. Flux de travail Git

1. Choisir une issue (voir la section 7) et vous l'assigner.
2. Créer une branche depuis `main` à jour : `feature/BE-03-auth-jwt`, `fix/…` ou `docs/…`.
3. Commiter au format `type(portée): résumé`, par exemple `feat(backend): ajoute l'authentification JWT`.
4. Ouvrir une pull request vers `main`, avec `Closes #n` dans la description.
5. Attendre la CI verte et l'approbation de l'autre membre. Le modèle de pull request liste les preuves à fournir.

`main` est protégée : pas de push direct, une approbation obligatoire, la branche doit être à jour avec `main`. La fusion se fait par squash et la branche est supprimée automatiquement.

## 6. Qualité et sécurité

Six contrôles doivent être verts pour fusionner :

| Contrôle | Ce qu'il fait | Équivalent local |
|---|---|---|
| `backend` | ruff, format, pytest, pour chaque dossier de `services/` | `ruff check .`, `ruff format --check .`, `python -m pytest` |
| `frontend` | eslint, prettier, tests, build | `npm run lint`, `npm run format:check`, `npm test`, `npm run build` |
| `gitleaks` | secrets dans tout l'historique | ne commitez jamais `.env` |
| `snyk` | vulnérabilités des dépendances, seuil « high » | — |
| `docker` | construction des images et analyse Snyk | `docker build services/traitement/`, `docker build frontend/` |
| `sonarqube` | qualité et couverture du code | — |

Un secret commité dans l'historique fait échouer gitleaks définitivement : si cela arrive, prévenez le binôme avant toute autre action. Les exceptions de sécurité acceptées sont dans `.snyk` et suivies dans [docs/04-devsecops/exceptions.md](04-devsecops/exceptions.md), chacune avec une date d'expiration.

Dependabot ouvre chaque mois des pull requests groupées de mises à jour, sans versions majeures. Elles suivent le même circuit de revue.

## 7. Où trouver quoi

| Besoin | Endroit |
|---|---|
| Tâches à faire | Issues GitHub. Filtrer par étiquette `team:backend` ou `team:frontend`, par priorité `prio:P0`, par jalon |
| Définition des tâches et dépendances | `scripts/github/issues_data.py` (identifiants BE-xx, FE-xx, DAT-xx…) |
| Périmètre et compétences BC05 | `docs/00-cadrage/note-de-cadrage.md` |
| Kafka local : sujets, publication, relecture | `docs/08-exploitation/kafka-local.md` |
| Décisions d'architecture (ADR) | `docs/01-architecture/adr/` (modèle : `000-modele.md`) |
| Contrats d'API (un par service) | `contracts/openapi/` |
| Contrats d'événements du bus, matrice des sujets, conformité | `contracts/` (`README.md`) |
| Décisions prises avec le professeur | `docs/07-gestion/decisions-professeur.md` |
| Risques et changements | `docs/07-gestion/` |
| Usage de l'IA | `docs/ia/journal-usage-ia.md` : inscrivez-y tout usage significatif |

Jalons : M1 le 01/11/2026 (socle et spécifications), M2 le 15/11 (données et back-end), M3 le 22/11 (front-end), M4 le 29/11 (IA et intégration), M5 le 06/12 (stabilisation), soutenance le 10/12/2026.

## 8. Tâches backend, dans l'ordre

| Ordre | Issue | Dépend de | Remarque |
|---|---|---|---|
| 1 | BE-01 Contrat OpenAPI v1 | GES-06 | Rédiger le brouillon avant la réunion avec le professeur |
| 2 | BE-02 Modèle SQLAlchemy et migrations Alembic | DAT-02 (schéma de données) | Le schéma vient des scripts SQL de `data/dwh/sql/` |
| 3 | BE-03 Authentification JWT et rôles | BE-01, BE-02 | `JWT_SECRET` vient de l'environnement, jamais du code |
| 4 | BE-04 Endpoints des indicateurs | BE-03, DAT-07 | Lecture depuis l'entrepôt PostgreSQL |
| 5 | BE-05 Audit et statistiques dans MongoDB | BE-03 | |
| 6 | BE-06 Erreurs, validation, versionnement | BE-01 | |
| 7 | BE-07 Tests unitaires et d'intégration | BE-04 | Le seuil de couverture est contrôlé par SonarQube |
| 8 | BE-08 Sécurité applicative | BE-03, CLD-11 | CORS, en-têtes, limitation de débit |

Vérifiez les dépendances dans l'issue avant de commencer : une tâche bloquée par une autre se prépare, mais ne se fusionne qu'après elle.

## 9. Problèmes fréquents

| Symptôme | Cause et solution |
|---|---|
| `address already in use` au `make up` | Port 5432 ou 27017 occupé : voir la section 2 |
| `permission denied` sur le socket Docker | Utilisateur absent du groupe `docker` : voir la section 1 |
| `make test` ou `make lint` : `ruff` ou `pytest` introuvable | Activer l'environnement virtuel : `source services/traitement/.venv/bin/activate` |
| `variable is not set` au lancement de Compose | `.env` manquant : `cp .env.example .env` |
| Le conteneur frontend seul s'arrête (`host not found in upstream "passerelle"`) | Normal hors Compose : nginx a besoin de la passerelle. Utilisez `make up` |
| CI rouge sur `docker` après un changement de Dockerfile | Reproduire en local : `docker build services/traitement/` puis `docker build frontend/` |
