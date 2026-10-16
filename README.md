# Novaria Core

Socle de données décisionnelles et d'intelligence artificielle d'UrbanHub.
Projet de Master 2 EADL (Expert en Architectures et Développement Logiciels) — MCCI Business School.
Référentiel : BC05. Soutenance : 10 décembre 2026.

| Couche | Technologie |
|---|---|
| Front-end | React + Vite (TypeScript) |
| Back-end | Python + FastAPI |
| Base relationnelle | PostgreSQL (métier et entrepôt décisionnel) |
| Base non relationnelle | MongoDB (journaux, statistiques, événements bruts, suivi des modèles) |
| Déploiement | Docker, AWS (Amazon Web Services) : ECS Fargate, ECR, RDS, S3, CloudWatch |
| Qualité et sécurité | SonarQube (qualité du code), Snyk (dépendances, code, conteneurs, IaC), gitleaks (secrets) |
| CI/CD | GitHub Actions |

## Démarrer en local

```bash
cp .env.example .env
make up                      # PostgreSQL, MongoDB, backend, frontend
# API : http://localhost:8000/docs   ·   Front : http://localhost:8080
make test && make lint
```

## Structure

| Dossier | Contenu |
|---|---|
| `backend/` | API FastAPI versionnée `/api/v1` |
| `frontend/` | Dashboard React + Vite |
| `data/` | ETL, entrepôt (SQL), prototypes flux et Big Data |
| `ml/` | Modèle de prévision, évaluation, registre |
| `automation/rpa/` | Robot Framework (RPA : Robotic Process Automation) |
| `infra/` | Terraform, définitions de tâches ECS |
| `docs/` | Cadrage, architecture (C4, ADR), spécifications, exploitation, soutenance |
| `planning/` | Fichiers ProjectLibre |
| `scripts/` | Création des issues GitHub, paramètres, secrets |

Règles de contribution : voir [CONTRIBUTING.md](CONTRIBUTING.md).
