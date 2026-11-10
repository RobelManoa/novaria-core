# Service reponse

Service Novaria Core « Réponse extérieure » (MS-12, issue #131) : un **contrôleur de feux simulé** par carrefour, qui applique les recommandations du traitement et les commandes manuelles des opérateurs **après des garde-fous de sécurité**, revient seul à un **plan à durées fixes** quand les recommandations manquent, publie `signal.status` et journalise les commandes dans MongoDB (`audit_logs`).

Le document de référence (règles de sécurité, modes, journal d'audit, preuves, choix à valider) est [docs/03-donnees/feux.md](../../docs/03-donnees/feux.md). Contrat d'API : [reponse.openapi.yaml](../../contracts/openapi/reponse.openapi.yaml). Événements : [signal-status](../../contracts/events/signal-status.schema.json), [traffic-recommendation](../../contracts/events/traffic-recommendation.schema.json).

## Ce que le service fait

| Élément | Où | Comportement |
|---|---|---|
| Garde-fous | `app/domain/safety.py` | Phases en conflit interdites, durée de phase de 10 à 90 s, cycle de 30 à 120 s, plan conforme au carrefour ; codes de refus stables |
| Contrôleur | `app/domain/controller.py` | Phases, dégagement de 4 s (tout au rouge), durée minimale jamais écourtée, modes `AUTOMATIC` / `MANUAL` / `DEGRADED_FIXED_PLAN`, commande manuelle prioritaire (une seule à la fois) |
| Service | `app/services/signals.py` | Un verrou, les contrôleurs, le journal **avant** l'effet d'une commande, la limite de débit par opérateur, les événements |
| Recommandations | `app/services/ingestion.py`, `app/adapters/kafka_io.py` | Lit `traffic.recommendations` (groupe `reponse`, offsets validés après l'envoi), rejette sur `errors.dlq` ce qui est hors contrat |
| Événements | `app/services/events.py`, `app/worker/runtime.py` | `signal.status` après chaque décision (clé = carrefour), file d'envoi en mémoire : les feux ne dépendent pas de Kafka |
| Journal | `app/adapters/mongo_audit.py` | `audit_logs` (compte `svc_reponse` : lire et insérer seulement) |
| API | `app/api/v1/signals.py` | `GET /signals`, `GET /signals/{id}`, `GET` et `POST /signals/{id}/commands` |
| Fils | `app/worker/runtime.py` | Phases, envoi, lecture : trois fils du même processus que l'API (l'état des feux est en mémoire) |

**Une seule instance.** L'état des feux est en mémoire : deux instances auraient deux états qui divergent. Un redémarrage ramène tous les carrefours au plan fixe (c'est voulu : un plan périmé ne survit pas à une panne).

## Configuration

Variables d'environnement (jamais de secret dans le code ; les secrets viennent de `.env`, voir [secrets](../../docs/04-devsecops/secrets.md)).

| Variable | Défaut | Sens |
|---|---|---|
| `MONGO_URL` | (aucune) | Journal d'audit, compte `svc_reponse`. Sans elle, **aucune commande manuelle n'est acceptée** (503) : on n'agit pas sans trace |
| `KAFKA_BOOTSTRAP_SERVERS` | (vide) | Sans elle, le service ne lit ni ne publie : les feux restent au plan fixe |
| `JWT_SECRET` | (aucune) | Clé de vérification des jetons de l'API métier (au moins 32 caractères) |
| `SIGNAL_INTERSECTIONS` | `INT_01` à `INT_06` | Carrefours équipés (réseau de démonstration) |
| `FIXED_PHASE_S` | `30` | Durée de chaque phase du plan fixe |
| `MAX_SILENCE_S` | `180` | Silence maximal avant le retour au plan fixe |
| `COMMAND_RATE_PER_MIN` | `10` | Commandes manuelles par opérateur et par minute (refus compris) |
| `KAFKA_GROUP_ID` | `reponse` | Groupe de lecture des recommandations |

## Commandes

Depuis ce dossier.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Environnement | `python3 -m venv .venv && . .venv/bin/activate` | `py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1` |
| Dépendances | `pip install -r requirements-dev.txt` | `pip install -r requirements-dev.txt` |
| Lancer | `uvicorn app.main:app --reload` | `uvicorn app.main:app --reload` |
| Tests et couverture | `pytest` | `pytest` |
| Tests d'intégration (Kafka et MongoDB jetables) | `make test-integration-reponse` | `py -3 scripts/dev/dev.py test-integration --service reponse` (depuis la racine) |
| Lint | `ruff check . && ruff format --check .` | `ruff check .; ruff format --check .` |
| Image | `docker build -t novaria-reponse .` | `docker build -t novaria-reponse .` |

## Organisation

```
app/main.py              application FastAPI ; le cycle de vie démarre et arrête les trois fils
app/domain/              le domaine pur : safety.py (garde-fous), controller.py (machine à états), model.py
app/services/            signals.py (service), ingestion.py, events.py, outbox.py, ports.py
app/adapters/            kafka_io.py, mongo_audit.py
app/worker/runtime.py    les trois fils : phases, envoi des événements, lecture
app/api/                 deps.py (composants, authentification), mapping.py, v1/ (health, signals)
app/core/                configuration, journaux, erreurs (format commun), jetons
app/schemas/             events.py (copie commune, MS-03), api.py
tests/unit/              tests unitaires (aucune base, aucun bus)
tests/contract/          conformité des modèles aux schémas de contracts/ et de la sonde au contrat OpenAPI
tests/integration/       Kafka et MongoDB réels (ignorés sans les variables NOVARIA_TEST_*)
```
