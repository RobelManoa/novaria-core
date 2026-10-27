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

## Organisation

`api/` (routes) → `services/` (règles métier) → `repositories/` (accès PostgreSQL et MongoDB). Les
contrats d'interface sont décrits dans `contracts/openapi/traitement.openapi.yaml` (source de vérité).

## Points ouverts

| Point | Position actuelle |
|---|---|
| Le service Docker Compose s'appelle encore `backend`, et le compte de base reste `svc_app` | Renommage et comptes dédiés avec MS-06 et MS-10 |
| Avenir du rôle « API métier » (utilisateurs, jetons) : ce service ou un service à part | Point ouvert n° 1 des [diagrammes C4](../../docs/01-architecture/c4/README.md) |
