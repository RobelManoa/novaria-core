# Raccourcis pour Linux et macOS. Sous Windows, utiliser directement :  py -3 scripts/dev/dev.py <commande>
# (mêmes commandes, sans installer make ; voir docs/08-exploitation/poste-de-travail.md).
PY ?= python3
DEV = $(PY) scripts/dev/dev.py
# Commandes qui importent les paquets de l'API (psycopg, argon2…) : le venv du dépôt s'il existe, sinon python3.
PY_API ?= $(if $(wildcard venv/bin/python),venv/bin/python,$(PY))
DEV_API = $(PY_API) scripts/dev/dev.py

.PHONY: help init-env up down health lock-deps ps logs dev-deps user-create api-run front-dev front-dev-stub forecast-stub report-stub front-dev-report-stub db-up db-migrate db-migrate-app db-status db-check db-check-events db-check-kpi etl-paris etl-nettoyer-paris etl-lot etl-package psql mongosh backup restore-check restore db-reset kafka-up kafka-topics kafka-roundtrip test test-integration test-integration-collecte test-integration-flux test-integration-alerte test-integration-reponse test-collecte-debit test-contracts test-etl lint format new-service quality-up quality-down hooks terraform-check drift-check

help:          ## Liste des commandes
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

init-env:      ## Crée .env avec des mots de passe aléatoires (une seule fois)
	$(DEV) init-env
up:            ## Démarre tout (bases, bus, 4 services, simulateur, passerelle, front-end) et vérifie chaque /health
	$(DEV) up
down:          ## Arrête et supprime les conteneurs (données conservées)
	$(DEV) down
health:        ## Interroge le /health de chaque conteneur
	$(DEV) health
lock-deps:     ## Recalcule les verrous de dépendances (make lock-deps N=alerte pour un seul service)
	$(DEV) lock-deps $(N)
ps:            ## État des conteneurs
	$(DEV) ps
logs:          ## Journaux (make logs S=collecte pour un seul service Compose)
	$(DEV) logs $(S)

dev-deps:      ## Installe les paquets Python de l'API et de l'ETL (dans venv/ s'il existe)
	$(DEV_API) dev-deps
user-create:   ## Crée un compte de l'API (make user-create U=robel ROLE=viewer) ; mot de passe saisi sans écho
	$(if $(U),,$(error Donner un nom : make user-create U=robel ROLE=viewer))
	$(DEV_API) user-create $(U) --role $(or $(ROLE),viewer)
api-run:       ## Lance l'API de traitement sur http://127.0.0.1:8000 (bases : db-up)
	$(DEV_API) api-run
front-dev:     ## Lance le front-end sur http://localhost:5173 (l'API doit tourner : api-run)
	$(DEV) front-dev

forecast-stub: ## MAQUETTE de GET /api/v1/forecasts devant l'API (route non implémentée) sur http://127.0.0.1:8001
	$(DEV) forecast-stub
front-dev-stub: ## Front-end dont les appels /api passent par la maquette des prévisions (page Prévisions)
	$(DEV) front-dev --stub
report-stub:   ## MAQUETTE de GET /api/v1/reports devant l'API (routes et robot absents) sur http://127.0.0.1:8002 ; make report-stub N=0 : liste vide
	$(DEV) report-stub $(if $(N),--count $(N),)
front-dev-report-stub: ## Front-end dont les appels /api passent par la maquette des rapports (page Rapports)
	$(DEV) front-dev --report-stub

db-up:         ## Démarre PostgreSQL et MongoDB, applique les migrations
	$(DEV) db-up
db-migrate:    ## Applique les migrations SQL en attente
	$(DEV) db-migrate
db-migrate-app: ## Applique les migrations Alembic du schéma app (compte svc_app)
	$(DEV) db-migrate-app
db-status:     ## État des bases et des migrations
	$(DEV) db-status
db-check:      ## Vérifie rôles, droits, collections et index
	$(DEV) db-check
db-check-events: ## Insère une mesure conforme (acceptée) et une sans provenance (refusée)
	$(DEV) db-check-events
db-check-kpi:  ## Recalcule les 5 indicateurs sur un jeu fabriqué (transaction annulée) et les compare aux vues
	$(DEV) db-check-kpi
etl-paris:     ## Ingère le comptage routier de Paris (make etl-paris DAY=2026-10-18) : fichier brut + journal MongoDB
	$(DEV) etl-paris --day $(DAY)
etl-nettoyer-paris: ## Nettoie le brut de Paris (make etl-nettoyer-paris DAY=2026-10-17) : propres, rejets, taux de rejet
	$(DEV) etl-nettoyer-paris --day $(DAY)
etl-lot:       ## Lot ETL planifié (make etl-lot DAY=2026-10-17 ; sans DAY : la veille) : ingestion, nettoyage de Paris
	$(DEV) etl-lot $(if $(DAY),--day $(DAY),)
etl-package:   ## Empaquette la logique ETL en dist/novaria-etl-<version>.zip (reproductible)
	$(DEV) etl-package
psql:          ## Ouvre psql (administrateur local)
	$(DEV) psql
mongosh:       ## Ouvre mongosh (administrateur local)
	$(DEV) mongosh
backup:        ## Sauvegarde PostgreSQL et MongoDB dans backups/
	$(DEV) backup
restore-check: ## Vérifie la dernière sauvegarde dans une base jetable
	$(DEV) restore-check
restore:       ## REMPLACE les données locales par la dernière sauvegarde (confirmation demandée)
	$(DEV) restore
db-reset:      ## SUPPRIME les données locales (confirmation demandée)
	$(DEV) db-reset

kafka-up:      ## Démarre Kafka (mode KRaft) et attend qu'il soit prêt
	$(DEV) kafka-up
kafka-topics:  ## Crée les 6 sujets du bus s'ils manquent et les vérifie
	$(DEV) kafka-topics
kafka-roundtrip: ## Publie mesure-valide.json sur iot.raw, le relit et le valide
	$(DEV) kafka-roundtrip

test:          ## Tests des services + frontend + scripts du poste
	@for d in services/*/; do (cd $$d && python -m pytest) || exit 1; done
	cd frontend && npm test
	$(PY) -m unittest discover -s scripts/dev
	$(PY) -m unittest discover -s data/etl/tests
	$(PY) -m unittest discover -s simulator/tests
test-integration: ## Tests de services/traitement contre PostgreSQL et MongoDB en conteneur (projet jetable) + rapport de couverture
	$(DEV) test-integration
test-integration-collecte: ## Tests de services/collecte contre Kafka et MongoDB en conteneur (projet jetable) + rapport de couverture
	$(DEV) test-integration --service collecte
test-integration-flux: ## Tests du flux (services/traitement) contre PostgreSQL migré, MongoDB et Kafka en conteneur (projet jetable)
	$(DEV) test-integration --service flux -- tests/integration/test_flux_stack.py
test-integration-reponse: ## Tests de services/reponse contre Kafka et MongoDB en conteneur (projet jetable) : garde-fous, mode dégradé, audit
	$(DEV) test-integration --service reponse
test-integration-alerte: ## Tests de services/alerte contre PostgreSQL migré et Kafka en conteneur (projet jetable) : délai jusqu'à l'alerte visible
	$(DEV) test-integration --service alerte
test-collecte-debit: ## Débit maximal de la collecte démarrée (make test-collecte-debit COLLECTE_URL=http://127.0.0.1:8001)
	$(PY) scripts/dev/bench_collecte.py --url $(or $(COLLECTE_URL),http://127.0.0.1:8001)
test-contracts: ## Valide les exemples et les cas invalides des contrats d'événements
	$(PY) -m unittest discover -s contracts/tests
test-etl:      ## Tests des pipelines d'ingestion (sans réseau ni base)
	$(PY) -m unittest discover -s data/etl/tests
test-simulator: ## Tests du simulateur de capteurs (déterminisme, contrat MS-03, anomalies ; jsonschema pour la conformité)
	$(PY) -m unittest discover -s simulator/tests
sim-scenarios: ## Liste les scénarios du simulateur de capteurs
	$(PY) simulator/app.py scenarios
sim-run:       ## Écrit un run complet pour IA-08 (make sim-run SCENARIO=heure-de-pointe SEED=42 ; dans var/runs/<run>)
	$(PY) simulator/app.py run --scenario $(or $(SCENARIO),heure-de-pointe) --seed $(or $(SEED),42) --out var/runs/run-$(or $(SCENARIO),heure-de-pointe)-$(or $(SEED),42)
lint:          ## Ruff sur chaque service, ESLint et Prettier sur le frontend
	@for d in services/*/; do (cd $$d && ruff check . && ruff format --check .) || exit 1; done
	cd frontend && npm run lint && npm run format:check
format:        ## Formate chaque service et le frontend
	@for d in services/*/; do (cd $$d && ruff check --fix . && ruff format .) || exit 1; done
	cd frontend && npx prettier --write src
new-service:   ## Crée services/<N> depuis le gabarit (make new-service N=alerte)
	$(DEV) new-service $(N)
drift-check:    ## Script de dérive (IA-06) : entrées de l'exécution la plus récente contre une référence ; make drift-check REF=<run_id> ; code 1 si dérive
	$(DEV) drift-check $(if $(REF),--reference-run $(REF),)
terraform-check: ## Contrôles Terraform sans compte AWS (Docker) : fmt, init, validate, tflint, Snyk IaC ; make terraform-check LOCK=1 : régénère le verrou
	$(DEV) terraform-check $(if $(LOCK),--lock,)
quality-up:    ## SonarQube Community Build local
	docker compose -f compose.quality.yml up -d
quality-down:
	docker compose -f compose.quality.yml down
