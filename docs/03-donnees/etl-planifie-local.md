# ETL planifié en local et équivalent AWS Glue (DAT-06)

> Issue #60. Critères : **le rejeu du chargement produit les mêmes totaux** ; **l'équivalent Glue est documenté**. Preuve :
> le [rapport de comparaison](rapport-rejeu-etl.md). Décisions de fond : [ADR-013](../01-architecture/adr/ADR-013-integration-donnees.md),
> [ADR-023](../01-architecture/adr/ADR-023-execution-locale-d-abord.md), [ADR-025](../01-architecture/adr/ADR-025-equivalents-locaux-des-services-aws.md).

## 1. Ce qui est livré

| Tâche de l'issue | Livrable | Statut |
|---|---|---|
| Packager la logique ETL | `data/etl/pyproject.toml`, archive reproductible `novaria-etl-<version>.zip` (`dev.py etl-package`) | Prouvé (même empreinte à chaque construction) |
| Documenter l'équivalent Glue (job, planification) sans l'exécuter | Section 6 de ce document | Documenté ; **Glue non exécuté** |
| Planifier l'exécution locale | `dev.py etl-lot`, `data/etl/planification/novaria-etl.cron` (Linux), `installer-tache-windows.ps1` (Windows) | Commande et modèles prouvés par des tests ; planificateurs réels : section 4 |
| Rejouer le chargement, mêmes totaux | `dev.py etl-charger` et `dev.py etl-rejouer`, [rapport](rapport-rejeu-etl.md) | Prouvé sous Docker, poste Windows ; poste Linux à rejouer |

## 2. Paquet

```bash
python3 scripts/dev/dev.py etl-package          # dist/novaria-etl-0.1.0.zip (Windows : py -3 scripts/dev/dev.py ...)
```

L'archive contient les paquets `pipelines` et `transforms`, `requirements.txt` et un `MANIFEST.txt` (SHA-256 de chaque
fichier). Elle est **déterministe** : ordre et dates fixés, aucun cache Python, donc les mêmes sources donnent la même
empreinte. Un job Glue ou un déploiement sans le dépôt prend cette archive telle quelle. `pyproject.toml` rend aussi le
dossier installable (`pip install data/etl`) et déclare trois commandes (`novaria-etl-lot`, `novaria-etl-charger`,
`novaria-etl-rejouer`) ; ses dépendances sont celles de `requirements.txt` (un test les compare).

## 3. Chargement idempotent des fenêtres de trafic

`python3 scripts/dev/dev.py etl-charger --file fenetres.csv --run-id <run>` contrôle un fichier de fenêtres puis l'écrit dans
`dwh.fact_traffic_window` avec le compte `svc_traitement`.

**Fichier d'entrée.** Placé dans `data/datasets/fenetres/` (dossier ignoré par git) et désigné par son nom : un chemin vers un autre dossier est refusé, comme pour le nettoyage de Paris. CSV UTF-8 séparé par des virgules, une fenêtre par ligne, colonnes de
`transforms/fenetres_trafic.py` (`road_segment_id, window_start, window_size_s, source_type, vehicle_count, flow_veh_per_min,
average_speed_kmh, occupancy_rate, max_queue_length_m, speed_ratio, sample_count, expected_sample_count, congestion_state,
classifier_version`). Le `run_id` est un paramètre du chargement, pas une colonne : c'est l'exécution d'origine.

**Clé d'idempotence.** La clé primaire de la table : `(road_segment_key, window_start, window_size_s, run_id)`. L'écriture est
un `INSERT … ON CONFLICT (clé) DO UPDATE … WHERE (valeurs) IS DISTINCT FROM (valeurs reçues)` : une ligne absente est créée,
une ligne présente et différente est mise à jour, une ligne présente et identique **n'est pas réécrite** (son `loaded_at`
reste celui du premier chargement). Tout le fichier s'écrit dans **une transaction** : un échec ne laisse rien à moitié chargé.

**Règles de contrôle** (une ligne refusée l'est pour la première règle violée, dans cet ordre ; elle va dans `dwh.etl_reject`,
jeu `fenetres_trafic`, avec la règle et le motif) :

| Règle | Refus si |
|---|---|
| `MISSING_REQUIRED` | une colonne obligatoire de la table est vide |
| `TYPE_INVALID` | identifiant de tronçon hors `ROAD_nnn`, instant sans fuseau ou non ISO 8601, entier ou décimal illisible |
| `OUT_OF_RANGE` | valeur hors des bornes de la table (débit, vitesse ≤ 200, occupation 0 à 1, entiers, taille de fenêtre autre que 60 ou 300 s) |
| `NOT_ALIGNED` | le début de fenêtre n'est pas un multiple de sa taille |
| `SPEED_WITHOUT_VEHICLE` | une vitesse est donnée alors que le nombre de véhicules est 0 (contrainte de la table) |
| `UNKNOWN_REFERENCE` | tronçon, état de congestion ou source absent des dimensions de l'entrepôt |
| `DUPLICATE_KEY` | même tronçon et même fenêtre qu'une ligne précédente du fichier (la première est retenue) |

Le refus par ligne remplace l'échec de tout le lot par PostgreSQL : une valeur invalide est tracée, le reste est chargé.
Les rejets d'un fichier sont **remplacés** à chaque chargement (comme ceux de Paris, [nettoyage](nettoyage-paris.md)) : les
rejouer ne les duplique pas. Si le nombre de rejets écrits diffère du nombre de lignes refusées, rien n'est chargé.

**Pas de données de Paris dans cette table.** Le comptage de Paris est horaire, sans état de congestion ni tronçon d'approche
(longueur, voies, vitesse limite) ; la table exige tout cela et sa fenêtre est de 60 ou 300 s. L'[ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md),
section 3.2, l'interdit : les jeux réels restent des fichiers. Les fenêtres chargées viennent du générateur de scénarios
(source `SIMULATED`), qui est une autre issue. En attendant, `data/etl/tests/echantillon_fenetres.py` fabrique de quoi
prouver le chargement : 24 tronçons du réseau de démonstration × 36 fenêtres de 5 minutes, valeurs par formule, jamais
présentées comme mesures.

```bash
python3 data/etl/tests/echantillon_fenetres.py --out data/datasets/fenetres/fenetres-demo.csv --defects   # 868 lignes dont 4 à refuser
```

## 4. Planifier le lot en local

Le lot (`dev.py etl-lot`, module `pipelines.lot`) enchaîne l'ingestion et le nettoyage de Paris pour **la veille en UTC**
(une journée complète), puis charge un fichier de fenêtres si `--windows` et `--run-id` sont donnés. Le nettoyage est sauté
si l'ingestion échoue ; le chargement est indépendant. Le code de sortie est 1 si une étape tentée échoue : le planificateur
voit l'échec. Rejouer un lot est sans effet de bord, car chaque étape est idempotente.

| Système | Mise en place | Retrait |
|---|---|---|
| **Linux** : `cron` | Remplacer `/CHEMIN/VERS/novaria-core` dans `data/etl/planification/novaria-etl.cron`, puis `crontab -e` et coller la ligne (chaque jour à 02:30, heure du poste) | `crontab -e`, supprimer la ligne |
| **Windows** : Planificateur de tâches | `powershell -ExecutionPolicy Bypass -File data\etl\planification\installer-tache-windows.ps1 -Heure 02:30` (tâche « Novaria ETL », compte courant, session ouverte, aucun mot de passe stocké) | même script avec `-Supprimer` |
| **Sans planificateur** | `python3 scripts/dev/dev.py etl-lot` à la main ou `make etl-lot` | — |

Prérequis communs : `dev.py db-up` lancé (PostgreSQL et MongoDB), `.env` présent, `pip install -r data/etl/requirements.txt`.
La sortie du lot est ajoutée à `var/log/etl-lot.log` (dossier ignoré par git). **Limite** : le poste doit être allumé à l'heure
dite ; la tâche Windows rattrape un passage manqué au prochain démarrage (`StartWhenAvailable`), le `cron` non (un lot manqué se
relance à la main avec `--day`).

| Cible AWS (non exécutée) | Équivalent local |
|---|---|
| EventBridge Scheduler (ou déclencheur Glue) lance le job | `cron`, Planificateur de tâches, commande `dev.py` ([ADR-025](../01-architecture/adr/ADR-025-equivalents-locaux-des-services-aws.md)) |
| Journal CloudWatch du job | `var/log/etl-lot.log` |
| Alarme sur échec du job | code de sortie 1 du lot ; `ALERTE` du taux de rejet ([nettoyage](nettoyage-paris.md)) |

## 5. Rejouer et comparer

```bash
python3 scripts/dev/dev.py etl-rejouer --file fenetres-demo.csv --run-id preuve-dat06 --from-scratch --report
```

Trois passes sur le même fichier et le même `run_id`, avec les totaux relevés **dans la table** après chacune : (1) chargement
initial ; (2) rejeu à l'identique ; (3) reprise après incident : un dixième des lignes du run est supprimé, puis le fichier est
rechargé. Les totaux comparés : nombre de lignes, somme des véhicules, somme du débit et **empreinte MD5 des lignes triées**
(sans `loaded_at`), qui détecte aussi une valeur modifiée à nombre de lignes égal. `--report` écrit le rapport à un emplacement fixe, `docs/03-donnees/rapport-rejeu-etl.md` (aucun chemin n'est accepté en argument) ; l'archive de l'étape 2 va toujours dans `dist/`. `--from-scratch` ne supprime que les lignes
du `run_id` donné. Code de sortie : 0 si les trois relevés sont égaux, 2 sinon. Le résultat est dans le
[rapport de comparaison](rapport-rejeu-etl.md).

**Lot entier, deux fois de suite** (30/10/2026, Windows, bases neuves sous Docker, `etl-lot --day 2026-10-17 --windows fenetres-demo.csv --run-id lot-dat06`, 54 s) :

| | 1re exécution | 2e exécution |
|---|---|---|
| Journal d'ingestion (MongoDB) | nouvelle entrée, reçu 1 fois | déjà journalisé, reçu 2 fois |
| Lignes de Paris retenues / refusées | 42 213 / 29 259 | 42 213 / 29 259 (`dwh.etl_reject` : 29 259 lignes, non doublées) |
| Fenêtres : créées / déjà présentes | 864 / 0 | 0 / 864 |
| Totaux de la table | 864 lignes, 58 695 véhicules, débit 11 739,00, empreinte `1cdeb260…` | identiques |
| Code de sortie | 0 | 0 |

## 6. Équivalent AWS Glue (documenté, non exécuté)

Aucun job Glue n'est créé ni lancé : l'exécution est locale d'abord ([ADR-023](../01-architecture/adr/ADR-023-execution-locale-d-abord.md)),
et un job Spark a un coût minimal par exécution. Cette section décrit ce qu'il faudrait créer, pour que l'écart soit connu.

### 6.1 Correspondance

| Local | Glue |
|---|---|
| `python -m pipelines.lot` | Job `novaria-etl-lot`, type `glueetl` (Spark, Python) |
| `novaria-etl-<version>.zip` | Archive déposée dans S3, passée par `--extra-py-files` |
| `requirements.txt` | `--additional-python-modules` (versions exactes) |
| `MONGO_URL`, `POSTGRES_URL` dans `.env` | Connexion Glue (VPC, sous-réseau privé) + AWS Secrets Manager |
| `var/` et `data/datasets/` | Compartiment S3 chiffré (port `ObjectStore`, ADR-025) |
| Dictionnaire de données | Catalogue de données Glue |
| `cron` / Planificateur de tâches | Déclencheur Glue `SCHEDULED` ou EventBridge Scheduler |
| `etl-rejouer` (totaux dans la table) | La même requête de totaux sur RDS, après chaque exécution |

### 6.2 Définition du job (Terraform, à titre de documentation)

Ce bloc **n'est pas** un fichier `.tf` du dépôt : il ne passe ni la validation ni l'analyse de Terraform et ne crée rien. Il
serait déposé dans `infra/` par l'issue d'infrastructure, après décision de coût.

```hcl
resource "aws_glue_job" "etl_lot" {
  name              = "novaria-etl-lot"
  role_arn          = aws_iam_role.glue_etl.arn      # S3 en lecture, Secrets Manager en lecture, journaux
  glue_version      = "5.0"                          # Spark 3.5, Python 3.11 (à vérifier avant exécution)
  worker_type       = "G.1X"
  number_of_workers = 2                              # minimum d'un job Spark
  timeout           = 60                             # minutes
  command {
    name            = "glueetl"
    script_location = "s3://<compartiment>/glue/lot.py"
    python_version  = "3"
  }
  default_arguments = {
    "--extra-py-files"              = "s3://<compartiment>/glue/novaria-etl-0.1.0.zip"
    "--additional-python-modules"   = "psycopg[binary]==3.3.6,pymongo==4.19.0"
    "--job-bookmark-option"         = "job-bookmark-disable"   # l'idempotence vient de la clé, pas du signet
    "--enable-continuous-cloudwatch-log" = "true"
  }
  connections       = [aws_glue_connection.rds.name]
  execution_property { max_concurrent_runs = 1 }     # deux lots ne se chevauchent pas, comme IgnoreNew côté Windows
}

resource "aws_glue_trigger" "etl_quotidien" {
  name     = "novaria-etl-quotidien"
  type     = "SCHEDULED"
  schedule = "cron(30 1 * * ? *)"                    # 01:30 UTC chaque jour : syntaxe AWS à six champs, toujours en UTC
  actions { job_name = aws_glue_job.etl_lot.name }
}
```

### 6.3 Ce qui change dans le code, et pourquoi

- **Le script du job** (`lot.py` dans S3) est une enveloppe de quelques lignes : il lit les paramètres, appelle `pipelines.lot`
  ou, pour une grande volumétrie, applique les mêmes règles de ligne (`transforms`, du zip) par partition Spark.
- **Le doublon** (`DUPLICATE_KEY`) se détecte sur tout le fichier : en Spark, par `row_number()` sur la clé, non plus par un
  dictionnaire en mémoire.
- **L'écriture ne peut pas être l'écriture JDBC « append » de Spark** : elle n'a pas d'« insérer ou mettre à jour ». Elle passe par
  `foreachPartition` et la **même requête** `ON CONFLICT … DO UPDATE` (`charger_entrepot.SQL_ECRITURE`). C'est ce qui garde
  la clé d'idempotence identique et rend les totaux comparables.
- **Python.** Glue 5.0 fournit Python 3.11 ; le paquet vise 3.12 comme les services. La compatibilité du code avec 3.11
  n'a pas été vérifiée : à tester avant tout lancement réel.
- **Pas de pythonshell** : ses versions de Python sont trop anciennes pour ce code.

### 6.4 Comparaison attendue quand le job sera exécuté

Même fichier, même `run_id` : le job doit laisser dans RDS les mêmes **lignes, véhicules, débit et empreinte** que l'exécution
locale. Un écart est un défaut, pas une tolérance. Tant que le job n'est pas exécuté, le rapport indique « non exécuté » et
n'annonce aucun total Glue.

## 7. Pile recommandée et écarts avec les décisions écrites

Pile proposée le 30/10/2026 pour le projet, rapprochée de ce que le dépôt documente et implémente.

| Besoin | Technologie proposée | Dans le dépôt |
|---|---|---|
| Transport des événements | Apache Kafka | Décidé ([ADR-009](../01-architecture/adr/ADR-009-bus-evenements.md)), local en mode KRaft |
| Traitement temps réel | Apache Flink | Décidé ([ADR-011](../01-architecture/adr/ADR-011-temps-reel-et-batch.md)) ; non implémenté |
| **ETL par lots** | **Apache Spark (PySpark)** | Spark décidé pour le Big Data ([ADR-016](../01-architecture/adr/ADR-016-big-data.md), DAT-08) ; l'ETL est en Python ([ADR-013](../01-architecture/adr/ADR-013-integration-donnees.md)) ; **Glue = Spark géré : section 6** |
| Intégration et ingestion | Apache NiFi | **Écarté** par l'ADR-013 (option E) : sources simples |
| Stockage distribué | SeaweedFS | **Non documenté** : l'ADR-025 prévoit un dossier local derrière le port `ObjectStore` ; SeaweedFS en serait un adaptateur S3 |
| Bases | MongoDB, PostgreSQL | Décidé et implémenté ([ADR-002](../01-architecture/adr/ADR-002-postgresql-mongodb.md)) |
| Orchestration ML | Kubeflow Pipelines | **Non documenté** |
| Infrastructure | Docker, Terraform | Décidé ([ADR-020](../01-architecture/adr/ADR-020-terraform.md), [ADR-021](../01-architecture/adr/ADR-021-docker-deploiement.md)) |
| Backend, interface | FastAPI, React + Vite | Décidé ([ADR-001](../01-architecture/adr/ADR-001-python-fastapi.md)) et implémenté |

**Ce que fait DAT-06 de cette pile** : l'équivalent Glue est décrit comme un job Spark, ce qui suit la proposition pour l'ETL par
lots ; le code reste en Python pour la chaîne locale, qui est la référence ([ADR-013](../01-architecture/adr/ADR-013-integration-donnees.md)).
**À décider avec Manoa Robel avant de les mettre en œuvre** : NiFi (l'ADR-013 l'a écarté), SeaweedFS et Kubeflow (aucun ADR) ; chacun
demande un ADR, ou une mise à jour de l'ADR-013 et de l'ADR-025, avant d'entrer dans le code.

## 8. Limites connues

- **DAT-05.** L'issue est marquée terminée sur GitHub, mais son code n'est ni sur `main` ni sur une branche distante au 30/10/2026 :
  ce chargeur a été écrit sans le voir. S'il existe chez Manoa Robel, il faut aligner avant toute fusion : une seule écriture dans
  la table (la requête de `charger_entrepot.SQL_ECRITURE` ou la sienne), jamais deux, et un seul format de fichier d'entrée.
- Les valeurs de `classifier_version` et les seuils d'états viennent de l'échantillon fabriqué (`seuils-v0`) ; ils ne valent pas décision ([ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md)).
- La preuve a été faite sous Windows (Docker Desktop). Sous Linux : [À COMPLÉTER par Manoa Robel].
- Le planificateur réel (cron, Planificateur de tâches) n'a pas été installé pendant la rédaction : les modèles sont contrôlés par des tests
  (commande, heure, absence de mot de passe), pas par un déclenchement observé. À observer une fois sur chaque système :
  [À COMPLÉTER par chaque membre].
