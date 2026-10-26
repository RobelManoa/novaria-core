# Service gabarit

Service Novaria Core, créé depuis `services/_gabarit` (voir `CONTRIBUTING.md`, « Créer un nouveau service »).

## Ce que le service fait déjà

| Élément | Où | Comportement |
|---|---|---|
| Sonde de santé | `app/api/v1/health.py` | `GET /api/v1/health` renvoie `status`, `version`, `revision`, `environment` (schéma `Health` du contrat) |
| Configuration | `app/core/config.py` | Variables d'environnement : `SERVICE_NAME`, `ENVIRONMENT`, `GIT_SHA`, `LOG_LEVEL`. Aucun secret dans le code |
| Journaux | `app/core/logs.py` | Une ligne JSON par événement sur la sortie standard, avec `correlation_id` |
| Corrélation | `app/core/logs.py` | Lit `X-Correlation-ID` (valeur sobre de 64 caractères au plus), le génère sinon, le renvoie dans la réponse |
| Image | `Dockerfile` | Construction en plusieurs étapes, utilisateur non-root (`appuser`, uid 10001), sonde `HEALTHCHECK` |

Exemple de ligne de journal :

```json
{"ts": "2026-10-27T09:15:02.481Z", "level": "INFO", "service": "gabarit", "logger": "app.access", "message": "requête traitée", "correlation_id": "0b1f3a52-7a77-4c4e-8f3e-2f1d2f5a9b11", "method": "GET", "path": "/api/v1/health", "status": 200, "duration_ms": 1.2}
```

## Commandes

Depuis ce dossier.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Environnement | `python3 -m venv .venv && . .venv/bin/activate` | `py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1` |
| Dépendances | `pip install -r requirements-dev.txt` | `pip install -r requirements-dev.txt` |
| Lancer | `uvicorn app.main:app --reload` | `uvicorn app.main:app --reload` |
| Tests et couverture | `pytest` | `pytest` |
| Lint | `ruff check . && ruff format --check .` | `ruff check .; ruff format --check .` |
| Image | `docker build -t novaria-gabarit .` | `docker build -t novaria-gabarit .` |

## Organisation

```
app/main.py             application FastAPI, middleware de corrélation
app/api/v1/             routes (versionnées)
app/core/               configuration et journaux
tests/unit/             tests unitaires
```

Quand le service grandit, ajouter `services/`, `repositories/` et `schemas/` sous `app/` selon l'[ADR-010](../../docs/01-architecture/adr/ADR-010-architecture-hexagonale.md) ; les contrats d'interface sont dans `docs/02-specifications/openapi.yaml`.
