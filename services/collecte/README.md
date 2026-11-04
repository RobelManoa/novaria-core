# Service collecte

Service Novaria Core, créé depuis `services/_gabarit` (voir `CONTRIBUTING.md`, « Créer un nouveau service »). Issue MS-08 (#127). Preuve complète, avec les chiffres : [collecte](../../docs/03-donnees/collecte.md).

> Critère de MS-08 : **tous les messages valides arrivent sur `iot.raw`, tous les invalides sur le sujet d'erreurs `errors.dlq`, les doublons sont ignorés.**

## Ce que le service fait

| Besoin | Comportement | Où |
|---|---|---|
| Réception HTTP, sans état entre deux requêtes | `POST /api/v1/measurements` : `202 ACCEPTED`, `202 DUPLICATE`, `422`, `503` (contrat `collecte.openapi.yaml`) | `app/api/v1/measurements.py` |
| Réception « MQTT simulé » | Même logique, reçue comme le recevrait un abonné MQTT (sujet et charge) ; rejeu d'un fichier du simulateur | `app/adapters/mqtt_sim.py`, `app/cli.py` |
| Validation contre le schéma | Schéma de l'événement puis règles entre champs ; un motif pour chaque refus | `app/services/validation.py` |
| Messages invalides vers le sujet d'erreurs, avec le motif | Message `novaria.error.rejected.v1` sur `errors.dlq` (charge d'origine gardée telle que reçue), copie dans MongoDB `rejects` | `app/services/ingestion.py` |
| Publication sur `iot.raw` | Clé = carrefour, accusé du broker attendu (`acks=all`, producteur idempotent) | `app/adapters/kafka_publisher.py` |
| Copie brute | MongoDB `raw_events`, compte `svc_collecte` (`find` et `insert` seulement) | `app/adapters/mongo_store.py` |
| Idempotence | Un `id` déjà reçu est ignoré (`202 DUPLICATE`) : ni publié, ni stocké une seconde fois ; index unique de MongoDB comme arbitre | `app/services/ingestion.py` |
| Sonde de santé, corrélation, journaux JSON | Gabarit, inchangés | `app/api/v1/health.py`, `app/core/logs.py` |
| Aucun secret dans les journaux | Filet de masquage (adresse MongoDB) | `app/core/redaction.py` |

## Configuration

Variables d'environnement, jamais de secret dans le code. Docker Compose fournit les trois premières.

| Variable | Rôle | Par défaut |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | Adresse du broker (`kafka:9092` dans Compose) | vide : chaque publication répond `503` |
| `MONGO_URL` | Adresse MongoDB du compte `svc_collecte` (**secret**) | absente : chaque mesure répond `503` |
| `MONGO_DB` | Base | `novaria` |
| `MAX_BODY_BYTES` | Taille maximale d'un message (1 024 à 1 048 576) | 65 536 |
| `KAFKA_PUBLISH_TIMEOUT_S` | Attente maximale de l'accusé du broker | 10 |
| `MONGO_TIMEOUT_MS` | Délai de sélection du serveur MongoDB | 3 000 |
| `LOG_LEVEL`, `ENVIRONMENT`, `GIT_SHA`, `SERVICE_NAME` | Gabarit | `INFO`, `local`, `dev`, `collecte` |

Le service **démarre sans le bus ni la base** et répond à sa sonde : tant qu'ils manquent, il refuse chaque mesure en `503` (rien n'est perdu, l'émetteur renvoie).

## Commandes

Depuis ce dossier, sauf mention contraire.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Environnement | `python3 -m venv .venv && . .venv/bin/activate` | `py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1` |
| Dépendances | `pip install -r requirements-dev.txt` | `pip install -r requirements-dev.txt` |
| Lancer | `uvicorn app.main:app --reload` | `uvicorn app.main:app --reload` |
| Tests et couverture (sans bus ni base ; la barrière est de 70 %) | `pytest` | `pytest` |
| Tests contre Kafka et MongoDB en conteneur (depuis la racine du dépôt) | `python3 scripts/dev/dev.py test-integration --service collecte` | `py -3 scripts/dev/dev.py test-integration --service collecte` |
| Rejouer un fichier du simulateur par l'entrée « MQTT simulé » | `python -m app.cli replay-mqtt mesures.jsonl --redeliver` | idem |
| Mesurer le débit maximal (depuis la racine, collecte démarrée) | `python3 scripts/dev/bench_collecte.py --url http://127.0.0.1:8001` | `py -3 scripts/dev/bench_collecte.py --url http://127.0.0.1:8001` |
| Lint | `ruff check . && ruff format --check .` | `ruff check .; ruff format --check .` |
| Image | `docker build -t novaria-collecte .` | `docker build -t novaria-collecte .` |

Envoyer un scénario du simulateur (MS-07) à la collecte démarrée par `dev.py up` : `python3 simulator/app.py run --scenario heure-de-pointe --collecte-url http://127.0.0.1:8001` (Windows : `py -3`).

## Débit maximal sur un poste

Mesure demandée par l'[ADR-001](../../docs/01-architecture/adr/ADR-001-python-fastapi.md), faite le 05/11/2026 avec `scripts/dev/bench_collecte.py` : l'image telle que livrée (un processus `uvicorn`), Kafka (un courtier, `acks=all`) et MongoDB dans le même Docker Desktop, sur un portable Windows modeste (AMD Ryzen 7 3700U, 5,9 Go de mémoire). Méthode, tableau complet et limites : [collecte](../../docs/03-donnees/collecte.md), section 10.

| Connexions simultanées | Messages par seconde | Médiane | p95 |
|---|---|---|---|
| 1 | 55 | 17 ms | 28 ms |
| 4 | 80 | 44 ms | 90 ms |
| 16 | 87 | 163 ms | 299 ms |
| **32** | **97** | 312 ms | 538 ms |
| 64 | 94 | 651 ms | 982 ms |

**Débit maximal mesuré : environ 97 messages par seconde** (reproduit : 97,0 puis 97,2), soit environ 40 fois le débit nominal du simulateur (2,4 par seconde). Au-delà de 32 connexions seule la latence augmente. Aucune perte ni erreur dans la mesure finale. C'est une borne basse : le client Python partage le processeur avec le service, Kafka et MongoDB, et on n'a **pas** établi lequel des quatre sature le premier.

## Organisation

```
app/main.py              application FastAPI : corrélation, erreurs imprévues, sécurité des journaux
app/api/v1/              routes : santé, réception des mesures
app/api/deps.py          assemblage du service d'ingestion (une instance par processus)
app/services/            validation.py (messages), ingestion.py (issues, idempotence, pannes)
app/adapters/            kafka_publisher.py, mongo_store.py, mqtt_sim.py
app/core/                configuration, journaux, erreurs `Problem`, masquage des secrets
app/schemas/events.py    modèles Pydantic des six événements du bus (copie commune, MS-03)
app/cli.py               rejeu d'un fichier de mesures par le « MQTT simulé »
tests/unit/              validation, ingestion avec faux bus et fausse base, API, adaptateurs, MQTT simulé
tests/contract/          mêmes décisions que contracts/validate_events.py, sortie réelle du simulateur
tests/integration/       Kafka et MongoDB réels : le critère de MS-08 de bout en bout
```

L'architecture suit l'[ADR-010](../../docs/01-architecture/adr/ADR-010-architecture-hexagonale.md) : le cœur (`services/`) ne connaît ni HTTP, ni Kafka, ni MongoDB ; les adaptateurs les branchent. Les contrats d'interface sont dans `contracts/openapi/collecte.openapi.yaml` (HTTP) et `contracts/events/` (messages).

## Limites

Écarts avec le dictionnaire et le simulateur, publication « au moins une fois », entrée MQTT simulée : [collecte](../../docs/03-donnees/collecte.md), sections 9 et 12.
