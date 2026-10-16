# Backend (Python + FastAPI)

Interface de programmation (API) REST versionnée sous `/api/v1`.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload      # http://localhost:8000/docs
pytest                             # tests + couverture (coverage.xml)
ruff check . && ruff format --check .
```

Organisation : `api/` (routes) → `services/` (règles métier) → `repositories/` (accès PostgreSQL et MongoDB).
Les contrats d'interface sont décrits dans `docs/02-specifications/openapi.yaml` (source de vérité).
