# Note de cadrage BC05 : Novaria Core

**Statut** : proposition à valider par le professeur (point de la réunion GES-06). **Auteurs** : Manoa Robel et Daddy Luciano. **Version** : 1.

## 1. Contexte et objectif

Novaria Core est le socle partagé d'UrbanHub. Il est réalisé par deux étudiants du Master 2 EADL (Expert en Architectures et Développement Logiciels), pour une soutenance le 10/12/2026. Seul le bloc de compétences BC05 (données décisionnelles et intelligence artificielle) est évalué. Cette note fixe le périmètre, le niveau visé pour chacune des 9 compétences du bloc et la preuve attendue.

## 2. Périmètre

- **Inclus** : BC05, « Concevoir et optimiser les architectures de données décisionnelles et automatiser les processus et flux métier par l'apport de l'IA », soit 9 compétences.
- **Hors périmètre** : BC01 à BC04, acquis en première année :
  - BC01 : Concevoir et modéliser l'architecture logicielle ;
  - BC02 : Manager les projets numériques ;
  - BC03 : Piloter l'intégration et le déploiement continu dans le Système d'Information (SI) ;
  - BC04 : Optimiser le SI par l'apport du Cloud Computing.
- **Implémenté** : fonctionnalité complète, intégrée au socle et testée.
- **Prototype ciblé** : réalisation limitée dont le rapport indique ce qu'elle démontre et ce qu'elle ne démontre pas.

## 3. Compétences, niveaux et preuves

Les identifiants renvoient au backlog GitHub du projet. DOC-08 (matrice de preuves) relie chaque compétence à son code, son test et sa documentation.

| Compétence | Niveau | Preuve attendue | Critère d'acceptation | Issues liées |
|---|---|---|---|---|
| Architectures de données décisionnelles | Implémenté | Entrepôt en étoile PostgreSQL, diagrammes C4 (contexte, conteneurs, composants) | Les scripts SQL créent le schéma sur une base vide ; les trois vues C4 portent les mêmes noms | DAT-02, DAT-05, DOC-03 |
| Processus ETL (Extract, Transform, Load : extraction, transformation, chargement) et intégration de données | Implémenté | Scripts d'ingestion, de nettoyage et de chargement | Le pipeline s'exécute de bout en bout, une seconde exécution ne crée pas de doublon et les rejets sont tracés | DAT-03 à DAT-06 |
| Processus décisionnels et modèles de données | Implémenté | Définition des indicateurs, requêtes SQL, endpoints, dashboard | Chaque indicateur se recalcule depuis sa source annoncée ; les valeurs du dashboard égalent celles de l'API | DAT-07, BE-04, FE-04 |
| Machine Learning (ML, apprentissage automatique) | Implémenté | Cadrage du cas d'usage, code de préparation, évaluation | Le cadrage précède l'entraînement ; le découpage est reproductible ; le modèle retenu bat la référence simple, ou l'écart est documenté | IA-01 à IA-03, FE-05 |
| Gestion et déploiement des pipelines MLOps (Machine Learning Operations) | Implémenté | Registre de modèles, pipeline d'entraînement, surveillance de dérive | Un modèle sous le seuil n'est pas enregistré ; la dérive simulée déclenche l'alarme | IA-04 à IA-06 |
| Documentation et spécifications techniques | Implémenté | Spécifications, contrat OpenAPI, ADR (Architecture Decision Record, fiche de décision d'architecture) | Chaque exigence a une priorité et une preuve ; les documents décrivent ce qui est livré | DOC-05, DOC-07, DOC-08 |
| Big Data et traitement massif (Hadoop, Spark) | Prototype ciblé | Prototype Spark sur Amazon EMR et son rapport | Le rapport indique ce que le prototype démontre et ce qu'il ne démontre pas | DAT-08 |
| Traitement de flux en temps réel (Kafka, Flink) | Prototype ciblé | Prototype Kafka et Flink et son rapport | Les agrégats par fenêtre sont visibles dans MongoDB et les limites sont documentées | DAT-09 |
| RPA (Robotic Process Automation, automatisation des tâches) | Prototype ciblé | Robot dans `automation/rpa/` | Un rapport hebdomadaire est produit sans intervention manuelle | IA-07, FE-06 |

## 4. Règles d'arbitrage des briques lourdes

- **ETL** : retenu, car les données urbaines sont hétérogènes.
- **Kafka et Flink** : réservés à une exigence de temps réel posée formellement ; sans elle, le niveau reste le prototype.
- **ML** : conditionné à un cas d'usage à forte valeur démontré (IA-01).
- **MLOps et RPA** : réalisés seulement si un modèle est retenu, ou si une tâche répétitive le justifie.

## 5. Validation

- Statut : proposition à valider par le professeur lors de la réunion GES-06, qui consigne la décision dans `docs/07-gestion/decisions-professeur.md`.
- Relecture croisée : Manoa Robel relit la partie de Daddy Luciano, et inversement.
- Date de validation : [À COMPLÉTER : date]
- Responsable de la validation : [À COMPLÉTER : nom]
