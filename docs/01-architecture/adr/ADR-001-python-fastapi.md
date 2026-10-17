# ADR-001 — Python 3.12 et FastAPI pour les services

| Champ | Valeur |
|---|---|
| Date | 17/10/2026 |
| Statut | Acceptée |
| Décideurs | Daddy Luciano, Manoa Robel |
| Validation du professeur | Non requise (choix d'outil) |
| Issues liées | BE-01, BE-06, MS-04, MS-05 |
| Compétences BC05 | Documentation et spécifications techniques, ETL (Extract, Transform, Load), Machine Learning |
| Complète | [ADR-010](ADR-010-architecture-hexagonale.md), [ADR-012](ADR-012-validation-contrats-zod.md) |

## 1. Problème

Chaque service de Novaria Core expose une API (Application Programming Interface, interface de programmation) REST (Representational State Transfer), traite des données, parfois entraîne ou interroge un modèle de Machine Learning (apprentissage automatique). Le choix du langage et du framework conditionne la vitesse de livraison (9 semaines pour 2 personnes), la qualité du contrat d'API et la possibilité de réutiliser le même code pour l'API, l'ETL et l'IA (Intelligence Artificielle).

## 2. Forces de décision

| Critère | Poids | Pourquoi |
|---|---|---|
| Écosystème données et IA | Fort | Le bloc BC05 demande ETL, Spark, Flink, scikit-learn : leurs interfaces Python existent toutes (pandas, PySpark, PyFlink, scikit-learn) |
| Contrat d'API généré | Fort | Le contrat OpenAPI est la source de vérité entre services et front-end |
| Vitesse de développement | Fort | Deux personnes, 9 semaines, quatre services |
| Performance d'entrée/sortie | Moyen | Les services attendent surtout le réseau et les bases de données |
| Compétence du binôme | Fort | Le binôme maîtrise déjà Python |
| Typage et validation | Moyen | Réduire les erreurs de format entre services |

## 3. Options comparées

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| **A. Python 3.12 + FastAPI** | OpenAPI généré automatiquement, validation Pydantic, I/O asynchrone, même langage que l'IA et l'ETL | Verrou global de l'interpréteur (GIL, Global Interpreter Lock) : un calcul lourd monopolise un cœur ; typage facultatif | **Retenue** |
| B. Python + Django REST framework | Administration et ORM (Object-Relational Mapping) intégrés | Plus lourd, contrat OpenAPI moins direct, asynchrone moins naturel | Écartée |
| C. Java 21 + Spring Boot | Très robuste, performance, écosystème Kafka et Flink natif | Deux langages avec l'IA, démarrage lent des conteneurs, courbe d'apprentissage | Écartée |
| D. Node.js + NestJS | Même langage que le front-end | Écosystème données et IA plus faible ; PySpark et scikit-learn hors d'atteinte | Écartée |
| E. Go | Performance, binaire unique léger | Pas d'écosystème IA ; temps de prise en main | Écartée |

## 4. Choix

Tous les services sont écrits en **Python 3.12** avec **FastAPI** (serveur ASGI — Asynchronous Server Gateway Interface — Uvicorn) et **Pydantic v2** pour les modèles de données. Les dépendances sont bornées dans `requirements.txt` (par exemple `fastapi>=0.115,<1.0`).

## 5. Conséquences

**Positives**

- Un seul langage pour l'API, l'ETL, l'entraînement et les tests : le gabarit de service (MS-04) est partagé par les quatre services.
- `/openapi.json` est produit à chaque démarrage et comparé au contrat versionné (tests `contract/`).
- Les modèles Pydantic servent aussi à valider les messages des événements ([ADR-012](ADR-012-validation-contrats-zod.md)).

**Compromis acceptés**

- Le GIL limite le calcul parallèle dans un processus. Les calculs lourds (fenêtres de flux, Spark, entraînement) s'exécutent dans leur moteur dédié ([ADR-011](ADR-011-temps-reel-et-batch.md)), pas dans le processus de l'API.
- Le code asynchrone cesse d'être asynchrone dès qu'un appel bloquant s'y glisse. Règle : un pilote de base de données asynchrone, ou un appel synchrone confié au pool de threads.
- Le dépôt contient deux langages (Python et TypeScript). Le contrat commun ([ADR-012](ADR-012-validation-contrats-zod.md)) sert de pont.

**Risques et parades**

| Risque | Parade |
|---|---|
| Dépendances Python non figées, build non reproductible | Fichier de verrouillage avec empreintes, décidé dans [ADR-018](ADR-018-devsecops.md) |
| Typage laissé de côté | Annotations obligatoires dans le gabarit, contrôle par ruff et revue croisée |

## 6. Plan de repli

Un service dont le besoin de latence dépasse ce que Python offre (par exemple le contrôleur de feux) peut être réécrit dans un autre langage sans toucher aux autres : les services ne se parlent que par contrat ([ADR-008](ADR-008-microservices.md)). Ce repli coûte une seconde chaîne d'outils et n'est pas prévu avant le 10/12/2026.

## 7. Vérification

- `ruff check`, `ruff format --check` et `pytest` verts en CI (Continuous Integration, intégration continue).
- Test de contrat : le fichier OpenAPI généré correspond au contrat de `contracts/openapi/`.
- Mesure du débit maximal d'un service sur un poste (MS-08), consignée dans la documentation du service.

## 8. Conditions de réexamen

- Un service dépasse son objectif de latence malgré l'optimisation et le profilage.
- FastAPI change de version majeure avec rupture de compatibilité.
