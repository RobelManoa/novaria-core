# Service alerte

Service Novaria Core (MS-11). Il lit les indicateurs de `traitement`, ouvre **une alerte par épisode** de congestion, de saturation ou de capteur muet, la fait vivre (créée, notifiée, acquittée, résolue), publie chaque changement sur `alerts.events` et le diffuse en direct au tableau de bord.

Preuve, mesure du délai et choix à valider : [alertes](../../docs/03-donnees/alertes.md).

## Deux processus, une image

| Processus | Commande | Rôle |
|---|---|---|
| **API** | `uvicorn app.main:app` (conteneur `alerte`) | Lire et agir sur les alertes, régler les règles, diffuser le flux SSE (`GET /api/v1/events/stream`). Il lit `alerts.events` depuis la fin et le relaie à ses clients |
| **Travailleur** | `python -m app.worker` (conteneur `alerte-worker`) | Lire `traffic.indicators`, évaluer les règles, écrire alertes, historique et boîte d'envoi, publier `alerts.events`, remettre les notifications simulées |

Une **seule instance** du travailleur : les séries de fenêtres consécutives des règles sont en mémoire. Un redémarrage la vide (une alerte peut arriver `min_windows - 1` fenêtres plus tard, jamais en double).

## Ce que le service fait

| Élément | Où | Comportement |
|---|---|---|
| Règles | `app/domain/rules.py` | `congestion.persistante` (état stabilisé par `traitement` au moins `state` pendant `min_windows` fenêtres), `anomalie.circulation` (`min_windows` fenêtres fluides mais saturées), `capteur.muet` (aucune mesure pendant `silence_s`). Réglables par l'API |
| Cycle de vie | `app/services/alerts.py` | CREATED → NOTIFIED → ACKNOWLEDGED → RESOLVED, jamais en arrière. **Une transaction** par changement : l'alerte, son historique et l'événement à publier |
| Anti-bruit | index unique partiel + `min_gap_s` | Au plus une alerte non résolue par type, tronçon et run ; une nouvelle alerte attend `min_gap_s` après l'ouverture de la précédente |
| Cause | `alertes.alert.cause` | `UNKNOWN` : une baisse de vitesse ne prouve pas un accident |
| Boîte d'envoi | `app/services/relay.py` | Publie les événements dans l'ordre, après l'accusé du broker (livraison au moins une fois) |
| Notification simulée | `app/adapters/channels.py` | Une ligne de journal, ou un `POST` JSON vers un webhook ; aucune donnée de personne |
| Flux en direct | `app/sse.py` | SSE : un message par changement d'état, un battement toutes les 30 s |
| API | `app/api/v1/` | Contrat `contracts/openapi/alerte.openapi.yaml`, jetons de l'API métier (`viewer` lit, `operator` agit, `admin` règle) |
| Erreurs | `app/core/errors.py` | `application/problem+json` (RFC 9457), 500 sans trace, 503 si la base manque |

## Configuration (variables d'environnement)

| Variable | Défaut | Sens |
|---|---|---|
| `POSTGRES_URL` | — (secret) | Schéma `alertes`, compte `svc_alerte` ; la forme `postgresql+psycopg://` de Compose est acceptée |
| `KAFKA_BOOTSTRAP_SERVERS` | vide | Adresse du broker ; vide : pas de publication ni de flux |
| `JWT_SECRET` | — (secret) | Clé de vérification des jetons de l'API métier (HS256) ; voir [alertes](../../docs/03-donnees/alertes.md), section 9 |
| `NOTIFICATION_CHANNEL`, `WEBHOOK_URL` | `log`, vide | `log` ou `webhook` ; l'adresse du webhook est un secret |
| `RULES_TTL_S`, `WORKER_POLL_MS`, `OUTBOX_BATCH` | 5, 200, 100 | Durée de vie des règles en mémoire, attente d'un message, taille d'un lot de publication |
| `SSE_HEARTBEAT_S`, `SSE_QUEUE_SIZE`, `SSE_ENABLED` | 30, 1000, vrai | Battement, file par client (au-delà il est coupé), flux actif |
| `HEARTBEAT_FILE` | vide | Fichier touché à chaque tour du travailleur : sonde du conteneur |

Aucune valeur par défaut pour un secret ; une valeur refusée n'est jamais recopiée dans l'erreur.

## Commandes

Depuis ce dossier.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Environnement | `python3 -m venv .venv && . .venv/bin/activate` | `py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1` |
| Dépendances | `pip install -r requirements-dev.txt` | `pip install -r requirements-dev.txt` |
| Lancer l'API | `uvicorn app.main:app --reload` | `uvicorn app.main:app --reload` |
| Lancer le travailleur | `python -m app.worker` | `python -m app.worker` |
| Tests et couverture (sans base ni bus) | `pytest` | `pytest` |
| **Tests d'intégration** (PostgreSQL migré et Kafka jetables) | `python3 scripts/dev/dev.py test-integration --service alerte` (depuis la racine) | `py -3 scripts/dev/dev.py test-integration --service alerte` |
| Lint | `ruff check . && ruff format --check .` | `ruff check .; ruff format --check .` |
| Image | `docker build -t novaria-alerte .` | `docker build -t novaria-alerte .` |

## Organisation

```
app/main.py              application FastAPI, middlewares, gestion d'erreurs
app/worker/              point d'entrée du travailleur (python -m app.worker) et sa boucle
app/domain/              modèle et règles : fonctions pures, sans base ni bus (ADR-010)
app/services/            cycle de vie, traitement d'un indicateur, relais, notification, ports
app/adapters/            PostgreSQL (psycopg), Kafka (kafka-python), canaux de notification
app/api/v1/              routes : alertes, règles, flux SSE, sonde de santé
app/sse.py               concentrateur de diffusion (du fil Kafka aux clients)
app/core/                configuration, journaux, erreurs, jetons, masquage des secrets
app/schemas/events.py    modèles Pydantic des six événements du bus (copie commune, MS-03)
tests/unit/              tests unitaires (faux bus, fausse base fidèle)
tests/contract/          conformité des modèles aux schémas de contracts/ et des routes au contrat OpenAPI
tests/integration/       PostgreSQL et Kafka réels : contraintes, flux complet, délai jusqu'au tableau de bord
```

Les fichiers `app/core/redaction.py` et `app/core/unhandled.py` sont les mêmes que ceux de `collecte` et `traitement` (aucune différence hors docstrings : `scripts/dev/test_gabarit.py`, `CODE_PARTAGE`).
