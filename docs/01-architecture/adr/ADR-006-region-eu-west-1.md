# ADR-006 — Région AWS (Amazon Web Services) eu-west-1 (Irlande)

| Champ | Valeur |
|---|---|
| Date | 17/10/2026 |
| Statut | Acceptée |
| Décideurs | Daddy Luciano, Manoa Robel |
| Validation du professeur | À consigner |
| Issues liées | CLD-09, CLD-10, CLD-11, GES-09 |
| Compétences BC05 | Architectures de données décisionnelles |
| Complété par | [ADR-007](ADR-007-compte-aws.md) |

> **Mise à jour du 20/10/2026 ([ADR-023](ADR-023-execution-locale-d-abord.md)).** Aucune ressource n'est créée. La région reste le choix de la cible documentée.

## 1. Problème

Toutes les ressources AWS se créent dans une région. Ce choix détermine les services disponibles (bus d'événements géré, traitement de flux, ETL (Extract, Transform, Load), entraînement), le prix, la latence et le lieu de stockage des données.

## 2. Forces de décision

| Critère | Poids |
|---|---|
| Disponibilité des services du projet (ECS Fargate, RDS (Relational Database Service), ECR (Elastic Container Registry), MSK (Managed Streaming for Apache Kafka), Glue, EMR (Elastic MapReduce), SageMaker, Managed Service for Apache Flink) | Fort |
| Prix des ressources | Fort |
| Aucune adhésion préalable ni quota exceptionnel à demander | Moyen |
| Latence depuis les utilisateurs et le binôme (Maurice, Madagascar) | Faible : tableau de bord et traitements asynchrones |
| Localisation des données | Moyen : données simulées, aucune donnée personnelle |

## 3. Options comparées

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| **A. eu-west-1 (Irlande)** | Région historique, catalogue de services très complet, documentation et exemples abondants, aucune activation spéciale | Latence de plusieurs centaines de millisecondes depuis Maurice (à mesurer) | **Retenue** |
| B. eu-west-3 (Paris) | Proximité du cadre français | Catalogue parfois plus restreint, prix légèrement différents | Écartée |
| C. eu-central-1 (Francfort) | Catalogue complet | Prix souvent plus élevés | Écartée |
| D. af-south-1 (Le Cap) | Plus proche de Maurice | Région à activer, catalogue plus restreint, tarifs plus élevés | Écartée |
| E. ap-south-1 (Mumbai) | Plus proche de Maurice que l'Europe | Gain de latence sans effet sur ce projet, moins de références et d'exemples utilisés par le binôme | Écartée |
| F. us-east-1 (Virginie) | Nouveautés en premier, prix bas | Éloignement, localisation des données moins défendable | Écartée |

## 4. Choix

Toutes les ressources sont créées dans **eu-west-1**. La variable `AWS_REGION` de GitHub et le fournisseur Terraform portent cette valeur ; aucune ressource n'est créée ailleurs (la facturation mondiale et la console globale restent les seules exceptions du compte).

## 5. Conséquences

**Positives**

- Un seul endroit où chercher les ressources, les coûts et les journaux.
- Les exemples et la documentation du projet correspondent à la région.

**Compromis acceptés**

- La latence depuis Maurice est supérieure à celle d'une région proche. Un tableau de bord interrogeant des API (Application Programming Interface, interface de programmation) asynchrones la supporte ; les indicateurs de latence du projet se mesurent entre services (même région), pas depuis le navigateur.
- Pas de reprise inter-régions : un incident régional n'est pas couvert (hors périmètre, consigné dans les limites).

**Risques et parades**

| Risque | Parade |
|---|---|
| Un service prévu manque ou est limité dans la région | Vérifier la disponibilité de chaque service dans la console avant d'écrire le Terraform correspondant (CLD-10) |
| Écart de prix | Le chiffrage s'appuie sur les tarifs publics de eu-west-1 avec leur date de consultation (GES-09) |

## 6. Plan de repli

Une autre région européenne s'obtient en changeant la variable `AWS_REGION` et le fournisseur Terraform ; les images et le code ne changent pas. Les noms de compartiments S3 (Simple Storage Service) et les ARN (Amazon Resource Names) écrits en dur sont proscrits pour garder ce repli peu coûteux.

## 7. Vérification

- `aws configure get region` et la variable GitHub `AWS_REGION` valent `eu-west-1`.
- Aucune ressource n'apparaît dans une autre région (revue de la console, CLD-21).

## 8. Conditions de réexamen

- Un service indispensable n'existe pas en eu-west-1.
- Le professeur impose une contrainte de localisation des données.
