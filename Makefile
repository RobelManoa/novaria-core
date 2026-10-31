# Raccourcis pour Linux et macOS. Sous Windows, utiliser directement :  py -3 scripts/dev/dev.py <commande>
# (mêmes commandes, sans installer make ; voir docs/08-exploitation/poste-de-travail.md).
PY ?= python3
DEV = $(PY) scripts/dev/dev.py
# Commandes qui importent les paquets de l'API (psycopg, argon2…) : le venv du dépôt s'il existe, sinon python3.
PY_API ?= $(if $(wildcard venv/bin/python),venv/bin/python,$(PY))
DEV_API = $(PY_API) scripts/dev/dev.py

.PHONY: help init-env up down health lock-deps ps logs dev-deps user-create api-run front-dev front-dev-stub forecast-stub db-up db-migrate db-migrate-app db-status db-check db-check-events db-check-kpi etl-paris etl-nettoyer-paris etl-lot etl-package psql mongosh backup restore-check restore db-reset kafka-up kafka-topics kafka-roundtrip test test-contracts test-etl lint format new-service quality-up quality-down hooks

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
test-contracts: ## Valide les exemples et les cas invalides des contrats d'événements
	$(PY) -m unittest discover -s contracts/tests
test-etl:      ## Tests des pipelines d'ingestion (sans réseau ni base)
	$(PY) -m unittest discover -s data/etl/tests
lint:          ## Ruff sur chaque service, ESLint et Prettier sur le frontend
	@for d in services/*/; do (cd $$d && ruff check . && ruff format --check .) || exit 1; done
	cd frontend && npm run lint && npm run format:check
format:        ## Formate chaque service et le frontend
	@for d in services/*/; do (cd $$d && ruff check --fix . && ruff format .) || exit 1; done
	cd frontend && npx prettier --write src
new-service:   ## Crée services/<N> depuis le gabarit (make new-service N=alerte)
	$(DEV) new-service $(N)
quality-up:    ## SonarQube Community Build local
	docker compose -f compose.quality.yml up -d
quality-down:
	docker compose -f compose.quality.yml down
