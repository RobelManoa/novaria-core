# Prototype de flux temps réel : Kafka local et Flink SQL (DAT-09)

Les mesures de capteurs du simulateur ([MS-07](../../simulator/README.md)) sont publiées sur le sujet `iot.raw` de Kafka, agrégées par fenêtre de 1 et de 5 minutes par **Apache Flink** (Flink SQL, temps d'événement), et les agrégats sont écrits dans **MongoDB**. Amazon MSK et le service géré Flink sont **documentés, non exécutés** ([ADR-023](../../docs/01-architecture/adr/ADR-023-execution-locale-d-abord.md)).

**Rapport : [docs/03-donnees/prototype-flux.md](../../docs/03-donnees/prototype-flux.md)** (ce que le prototype démontre, ce qu'il ne démontre pas, mesures, équivalent MSK).

Les données sont **simulées**. Le prototype est isolé : il a ses fichiers Compose, son image et son compte MongoDB, et ne fait pas partie des quatre services ([ADR-008](../../docs/01-architecture/adr/ADR-008-microservices.md)). Le moteur de production du flux reste le consommateur Python de `services/traitement` ([flux](../../docs/03-donnees/flux.md), section 3) ; ce prototype éprouve l'autre branche de l'[ADR-011](../../docs/01-architecture/adr/ADR-011-temps-reel-et-batch.md).

## Contenu

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image Flink 1.20.5 (Java 17) + connecteurs Kafka 3.4.0 et MongoDB 2.0.0, **épinglés par SHA-256** ; l'image de base l'est par son empreinte |
| `compose.yml` | S'ajoute au `docker-compose.yml` de la racine : JobManager, TaskManager, mémoire bornée pour tenir dans 3 Go |
| `sql/agregats.sql` | Le job : source Kafka, filigrane de 10 s, retard autorisé de 30 s, deux `TUMBLE` (1 et 5 min), écriture idempotente dans MongoDB |
| `streaming/simulateur.py` | Rejoue le simulateur MS-07 (même scénario, même graine, mêmes messages) |
| `streaming/recalcul.py` | Recalcul par lots, en Python, des mêmes agrégats : la vérité de référence |
| `streaming/verifier.py` | Compare les documents de MongoDB au recalcul (valeurs, fenêtres manquantes, en trop) |
| `streaming/mongo.py` | Scripts `mongosh` : collection, validateur, compte d'écriture à droits minimaux, lecture |
| `streaming/sql.py` | Rendu du SQL (adresse et mot de passe de MongoDB), sans jamais écrire le texte rendu |
| `streaming/cli.py` | Les commandes (`dev.py flux-proto …`) |
| `tests/` | Tests sans Docker : recalcul, rendu SQL, comparaison, commandes |

## Lancer

Docker est la seule exigence ; `.env` doit exister (`python scripts/dev/dev.py init-env`). La mémoire de la machine virtuelle de Docker Desktop doit être d'au moins 3 Go. Premier lancement : 1,4 Go d'image Flink à télécharger.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Tout, dans un projet Compose jetable (ports libres, démonté à la fin) | `python3 scripts/dev/dev.py flux-proto demo` | `py -3 scripts/dev/dev.py flux-proto demo` |
| Construire l'image | `python3 scripts/dev/dev.py flux-proto build` | `py -3 scripts/dev/dev.py flux-proto build` |
| Démarrer Kafka, MongoDB, Flink et préparer MongoDB | `python3 scripts/dev/dev.py flux-proto up` | `py -3 scripts/dev/dev.py flux-proto up` |
| Envoyer le job SQL | `python3 scripts/dev/dev.py flux-proto job` | `py -3 scripts/dev/dev.py flux-proto job` |
| Publier un essai du simulateur | `python3 scripts/dev/dev.py flux-proto produire --duree 12m` | `py -3 scripts/dev/dev.py flux-proto produire --duree 12m` |
| Comparer MongoDB au recalcul | `python3 scripts/dev/dev.py flux-proto verifier --duree 12m` | `py -3 scripts/dev/dev.py flux-proto verifier --duree 12m` |
| Tout arrêter, et effacer les données | `python3 scripts/dev/dev.py flux-proto down --volumes` | idem avec `py -3` |
| Tests sans Docker | `python3 -m unittest discover -s tests -t .` (depuis `data/streaming`) | `py -3 -m unittest discover -s tests -t .` |

Pour une anomalie, ajouter `--anomalie` (répétable) : `--anomalie "doublon:sensor=SENSOR_001,at=+20,lag=5" --anomalie "retard:sensor=SENSOR_010,at=+40,delay=25"` ([simulateur, section 6](../../simulator/README.md)). Le même essai doit être donné à `produire` et à `verifier` : le recalcul relance le simulateur avec les mêmes réglages et retrouve les mêmes messages.

Le tableau de bord de Flink est sur `http://127.0.0.1:8081` (`FLINK_PORT`). Dans `mongosh` : `db.stream_window_aggregates.find().sort({window_end: -1}).limit(5)`.

## Secrets

Le job écrit dans MongoDB avec un compte **dédié** (`svc_flux_proto`) qui n'a que `find`, `insert` et `update` sur la collection `stream_window_aggregates`. Son mot de passe est la variable `MONGO_PASSWORD_FLUX_PROTO` : `flux-proto up` la génère et l'ajoute à `.env` (ignoré par Git) si elle manque ; la démonstration jetable ne l'écrit nulle part. Il passe par l'environnement des commandes et par l'entrée standard du client SQL de Flink, jamais par un argument ni par un fichier du dépôt. **Limite** : le job Flink garde l'adresse de MongoDB, mot de passe compris, dans sa configuration ; le tableau de bord de Flink (réseau local seulement) peut l'afficher. Sur AWS, l'adresse viendrait de Secrets Manager ([documenté](../../docs/03-donnees/prototype-flux.md), section 7).
