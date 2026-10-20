# Raccourcis pour Linux et macOS. Sous Windows, utiliser directement :  py -3 scripts/dev/dev.py <commande>
# (mêmes commandes, sans installer make ; voir docs/08-exploitation/poste-de-travail.md).
PY ?= python3
DEV = $(PY) scripts/dev/dev.py

.PHONY: help init-env up down ps logs db-up db-migrate db-status db-check psql mongosh backup restore-check restore db-reset test test-contracts lint format quality-up quality-down hooks

help:          ## Liste des commandes
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

init-env:      ## Crée .env avec des mots de passe aléatoires (une seule fois)
	$(DEV) init-env
up:            ## Démarre tout : bases, migrations, backend, frontend
	$(DEV) up
down:          ## Arrête tout (données conservées)
	$(DEV) down
ps:            ## État des conteneurs
	$(DEV) ps
logs:          ## Journaux (make logs S=backend pour un seul service)
	$(DEV) logs $(S)

db-up:         ## Démarre PostgreSQL et MongoDB, applique les migrations
	$(DEV) db-up
db-migrate:    ## Applique les migrations SQL en attente
	$(DEV) db-migrate
db-status:     ## État des bases et des migrations
	$(DEV) db-status
db-check:      ## Vérifie rôles, droits, collections et index
	$(DEV) db-check
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

test:          ## Tests backend + frontend + scripts du poste
	cd backend && python -m pytest
	cd frontend && npm test
	$(PY) -m unittest discover -s scripts/dev
test-contracts: ## Valide les exemples et les cas invalides des contrats d'événements
	$(PY) -m unittest discover -s contracts/tests
lint:
	cd backend && ruff check . && ruff format --check .
	cd frontend && npm run lint && npm run format:check
format:
	cd backend && ruff check --fix . && ruff format .
	cd frontend && npx prettier --write src
quality-up:    ## SonarQube Community Build local
	docker compose -f compose.quality.yml up -d
quality-down:
	docker compose -f compose.quality.yml down
