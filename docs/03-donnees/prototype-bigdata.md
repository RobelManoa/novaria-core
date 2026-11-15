# Prototype Big Data : PySpark en mode local contre l'ETL Python (DAT-08)

| Champ | Valeur |
|---|---|
| Issue | #83 (DAT-08) |
| Compétence BC05 | Big Data et traitement massif (Hadoop, Spark), niveau « Prototype ciblé » |
| Décisions | [ADR-016](../01-architecture/adr/ADR-016-big-data.md) (prototype Spark sans cluster Hadoop), [ADR-023](../01-architecture/adr/ADR-023-execution-locale-d-abord.md) (exécution locale, aucune ressource AWS), [ADR-025](../01-architecture/adr/ADR-025-equivalents-locaux-des-services-aws.md) (équivalents locaux) |
| Code | [`data/bigdata/`](../../data/bigdata/README.md) |
| Tests | `data/bigdata/tests/`, `scripts/dev/test_bigdata.py` |
| Date des mesures | 15/11/2026 |

Abréviations : AWS (Amazon Web Services), EMR (Elastic MapReduce, Spark géré d'AWS), S3 (Simple Storage Service, stockage d'objets d'AWS), IAM (Identity and Access Management, gestion des identités et des accès), ETL (Extract, Transform, Load, extraction, transformation, chargement), CSV (Comma-Separated Values, valeurs séparées par des virgules), CRC-32 (Cyclic Redundancy Check, contrôle de redondance cyclique), PSS (Proportional Set Size, mémoire proportionnelle d'un processus), JVM (Java Virtual Machine, machine virtuelle Java), CI (Continuous Integration, intégration continue).

@@CORPS@@
