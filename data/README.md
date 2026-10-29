# Données

- `etl/` : pipelines d'ingestion, de nettoyage et de chargement (Python) + tests. `etl/pipelines/` : ingestion du comptage routier de Paris (DAT-03, [mode d'emploi](../docs/03-donnees/ingestion-paris.md)) et nettoyage (DAT-04, [règles et rejets](../docs/03-donnees/nettoyage-paris.md)) ; `etl/transforms/` : les règles de qualité, fonctions pures ; `python -m unittest discover -s data/etl/tests` pour les tests
- `dwh/sql/` : vues d'indicateurs (KPI : Key Performance Indicator) et requêtes analytiques. **Les tables** (`app`, `dwh`, `alertes`) sont créées par les migrations de [`db/postgres/migrations`](../db/postgres/migrations) ([ADR-024](../docs/01-architecture/adr/ADR-024-bases-de-donnees-locales.md)).
- `streaming/` : prototype Kafka local + Flink (Amazon MSK (Managed Streaming for Apache Kafka) documenté, non exécuté : [ADR-023](../docs/01-architecture/adr/ADR-023-execution-locale-d-abord.md))
- `bigdata/` : prototype PySpark en mode local (Amazon EMR (Elastic MapReduce) documenté, non exécuté)
- `datasets/` : sources documentées, données ignorées par Git

Référence des champs, unités et règles de qualité : [dictionnaire de données](../docs/03-donnees/dictionnaire-de-donnees.md).
