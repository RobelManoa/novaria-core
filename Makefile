.PHONY: up down logs test lint format quality-up quality-down hooks
up:            ## Démarre l'environnement local
	docker compose up --build -d
down:          ## Arrête l'environnement local
	docker compose down
logs:
	docker compose logs -f backend
test:          ## Tests backend + frontend
	cd backend && python -m pytest
	cd frontend && npm test
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
