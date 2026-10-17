# Registre des demandes

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 17/10/2026
Issue de suivi : GES-05

Ce registre consigne chaque exigence et chaque demande nouvelle avec un statut, une équipe, un jalon et les issues qui la réalisent. Il remplace la lecture dispersée des présentations et sert de référence au moment des arbitrages.

## Mode d'emploi

- Toute demande nouvelle (du professeur, du binôme ou d'un tiers) reçoit une ligne et un identifiant. Une ligne n'est jamais supprimée : on change son statut et on note la date.
- Statuts : **Incluse** (dans le périmètre), **Exclue** (hors périmètre, avec la raison), **À arbitrer** (décision attendue).
- Colonne « Validation professeur » : **À consigner** tant que la réponse du professeur n'est pas écrite ici avec sa date. La présentation « Novaria Core : socle d'UrbanHub » (version du 15/10/2026) a été remise au professeur comme proposition soumise à validation ; ses réponses se consignent dans `docs/07-gestion/decisions-professeur.md` (issue GES-06), puis dans ce registre.
- Tout changement de périmètre s'écrit aussi dans `docs/07-gestion/journal-changements.md`.
- Abréviations : API (Application Programming Interface, interface de programmation), AWS (Amazon Web Services), CI/CD (Continuous Integration / Continuous Delivery), IAM (Identity and Access Management), WBS (Work Breakdown Structure, structure de découpage du projet).

## 1. Exigences de la proposition présentée au professeur

Source : présentation « Novaria Core : socle d'UrbanHub » (diapositives indiquées), consignes du professeur et présentation de découverte.

| ID | Demande | Source | Statut | Équipe · Jalon | Issues liées | Validation professeur |
|---|---|---|---|---|---|---|
| R-01 | Tableau de bord React relié au back-end par API REST (Representational State Transfer) | Diapo 4 | Incluse | Front-end · M3 | FE-01 à FE-08, MS-14 | À consigner |
| R-02 | Contrats d'API documentés avec OpenAPI, contrôle des droits, validation des formats de requêtes | Diapo 4 | Incluse | Back-end · M1 | BE-01, MS-03, MS-13 | À consigner |
| R-03 | Base SQL (Structured Query Language) relationnelle : schémas normalisés, intégrité référentielle, migrations versionnées | Diapo 4 | Incluse | Données · M2 | DAT-02, BE-02, MS-10 | À consigner |
| R-04 | Base NoSQL (Not Only SQL) pour les statistiques et les journaux d'audit | Diapo 4 | Incluse | Données · M2 | BE-05, MS-08, MS-12 | À consigner |
| R-05 | Diagrammes C4, modèles de données et procédures de reprise documentés | Diapo 4 | Incluse | Documentation · M1 | DOC-03, DAT-02, DOC-06 | À consigner |
| R-06 | Parcours fonctionnel minimal de bout en bout d'abord, puis extension progressive | Diapo 5 | Incluse | Les deux · M2 | MS-15, CLD-13 | À consigner |
| R-07 | Scénarios d'erreur éprouvés, tests consignés, résultats et limites documentés | Diapo 5 | Incluse | Cloud · M4 | CLD-13, CLD-14, MS-15 | À consigner |
| R-08 | Chaîne DevSecOps : Git à branches protégées, construction des conteneurs, tests et validation des contrats, détection de secrets, audit des dépendances | Diapo 7 | Incluse | Cloud · M1 | CLD-02 à CLD-08, MS-05 | À consigner |
| R-09 | Image immuable, versionnée et signée | Diapo 7 | À arbitrer | Cloud · M4 | Aucune (voir écart E-02) | À consigner |
| R-10 | Déploiement automatisé sur AWS avec vérification : sondes de santé, contrôle des accès | Diapo 7 | Incluse | Cloud · M1 à M4 | CLD-09 à CLD-12, MS-17 | À consigner |
| R-11 | Journaux centralisés, sauvegardes SQL planifiées, procédure de restauration documentée | Diapo 7 | Incluse | Cloud · M4 | CLD-14, CLD-15, DOC-06 | À consigner |
| R-12 | Politique IAM de moindre privilège | Diapo 7 | Incluse | Cloud · M1 | CLD-09, CLD-18 | À consigner |
| R-13 | Chiffrage AWS fondé sur l'inventaire réel des ressources, sans estimation financière non vérifiée | Diapos 7 et 9 | Incluse | Gestion · M5 | GES-09 | À consigner |
| R-14 | Planification dans ProjectLibre : WBS, charges, dépendances, chemin critique, diagramme de Gantt | Diapo 8 | Incluse | Gestion · M1 | GES-08, GES-10 | À consigner |
| R-15 | Plan DevSecOps par équipe dans ProjectLibre avec calcul des coûts du projet | Consigne du professeur | Incluse | Gestion · M1 | GES-08, GES-10 | À consigner |
| R-16 | Revues de code et validations croisées sur chaque livrable | Diapo 8 | Incluse | Les deux · continu | CLD-08, GES-17 | À consigner |
| R-17 | Registre des risques, matrice des dépendances et journal des arbitrages | Diapo 2 | Incluse | Gestion · M1 | GES-07, GES-12 | À consigner |
| R-18 | Contrats d'intégration et standards techniques pour accueillir d'autres projets UrbanHub | Présentation de découverte, diapo 11 | Incluse | Documentation · M1 | MS-03, DOC-05 | À consigner |
| R-19 | Soutenance du 10/12/2026 avec démonstration | Diapos 1 et 9 | Incluse | Les deux · M6 | GES-14, GES-15 | À consigner |

## 2. Briques du bloc de compétences BC05

Source : diapositive 6 de la présentation (« évaluer le besoin réel avant d'ajouter une brique lourde »).

| ID | Brique | Condition indiquée | Statut | Équipe · Jalon | Issues liées | Validation professeur |
|---|---|---|---|---|---|---|
| B-01 | ETL (Extract, Transform, Load) et intégration de données | Retenue si les volumes et l'hétérogénéité des données exigent un pipeline dédié | Incluse | Données · M2 | DAT-03 à DAT-06, MS-08, MS-09 | À consigner |
| B-02 | Données décisionnelles : modélisation analytique et indicateurs | À cadrer selon les besoins de reporting | Incluse | Données · M2 | DAT-02, DAT-07, MS-10 | À consigner |
| B-03 | Kafka et Flink : traitement de flux en temps réel | Réservé si une exigence stricte de temps réel est formellement posée | À arbitrer | Données · M1 (décision), M2 | MS-02, MS-09, DAT-09 | À consigner |
| B-04 | Machine Learning (apprentissage automatique) | Conditionné à un cas d'usage à forte valeur démontré | À arbitrer | IA · M4 | IA-01 à IA-03 | À consigner |
| B-05 | MLOps (Machine Learning Operations) | Uniquement si un modèle ML est retenu | À arbitrer | IA · M4 | IA-04 à IA-06 | À consigner |
| B-06 | RPA (Robotic Process Automation) | Uniquement si une tâche répétitive le justifie | À arbitrer | IA · M4 | IA-07 | À consigner |
| B-07 | Big Data (Hadoop, Spark) | Absent de la proposition ; prototype prévu au backlog | À arbitrer | Données · M4 | DAT-08 | À consigner |

## 3. Demandes nouvelles et changements de périmètre

| ID | Date | Demande | Origine | Statut | Équipe · Jalon | Issues liées | Validation professeur |
|---|---|---|---|---|---|---|---|
| C-01 | 17/10/2026 | Construire Novaria Core en microservices depuis zéro : collecte, traitement, alerte usager, réponse extérieure ; chaque service a l'architecture qui lui convient | Binôme (Manoa Robel) | Incluse | Les deux · M1 à M4 | MS-01 à MS-17 | À demander (la topologie présentée décrit un seul back-end) |
| C-02 | 17/10/2026 | Service de collecte alimenté par des données IoT (Internet of Things) simulées | Binôme | Incluse | Données · M2 | MS-07, MS-08 | À demander (voir écart E-04) |
| C-03 | 17/10/2026 | Service d'alerte usager : alertes envoyées aux usagers et consultables sur le tableau de bord | Binôme | Incluse | Back-end, Front-end · M2, M3 | MS-11, MS-14 | À demander |
| C-04 | 17/10/2026 | Service de réponse extérieure : gestion des feux de circulation, le trafic routier étant l'exemple retenu en première année du master | Binôme | Incluse | Back-end · M2 | MS-12 | À demander |

## 4. Exclusions

| ID | Demande exclue | Raison | Source | Validation professeur |
|---|---|---|---|---|
| X-01 | Évaluation des blocs BC01 à BC04 | Acquis en première année du master | Binôme | À consigner |
| X-02 | Intégration effective avec Novaria Signal et les autres services urbains (mobilité, énergie, open data) | Aucune intégration ni dépendance de calendrier entre promotions n'est présumée ; seuls les contrats d'intégration sont préparés (R-18) | Présentation de découverte, diapo 11 | À consigner |
| X-03 | Pilotage de feux de circulation réels (matériel) | Le contrôleur de feux est simulé | Proposition du binôme | À demander |
| X-04 | Hébergement hors AWS | AWS est le seul cloud du projet | Binôme | À consigner |
| X-05 | Estimation financière AWS avant l'inventaire des ressources | Règle de rigueur budgétaire | Diapo 7 | À consigner |

## 5. Points à arbitrer avec le professeur (issue GES-06)

1. Niveau de chaque compétence BC05 : Implémenté ou Prototype ciblé (B-01 à B-07).
2. Données : simulateur seul ou calé sur un jeu de données urbaines ouvert (C-02, DAT-01).
3. Équipes à planifier dans ProjectLibre (R-14, R-15).
4. Taux journalier, devise et plafond de dépense AWS (R-13).
5. Cahier des charges fonctionnel et validation des contrats d'API et de la topologie, microservices compris (R-02, C-01 à C-04).
6. Exigence formelle de temps réel, qui conditionne Kafka et Flink (B-03).

## 6. Écarts constatés à traiter

| ID | Écart | Action proposée | Responsable | Statut |
|---|---|---|---|---|
| E-01 | La topologie présentée au professeur (tableau de bord, un back-end, une base SQL, une base NoSQL) diffère de l'architecture en microservices (C-01) | Informer le professeur et faire valider l'ADR-008 | Les deux | Ouvert |
| E-02 | « Image signée » (diapo 7) n'a aucune issue | Créer une issue (signature des images) ou retirer l'engagement avec l'accord du professeur | Manoa Robel | Ouvert |
| E-03 | Big Data (Hadoop, Spark) est un prototype du backlog mais n'apparaît pas dans la proposition | Le présenter comme brique à arbitrer (B-07) | Les deux | Ouvert |
| E-04 | Le choix d'un jeu de données ouvert (DAT-01) et la simulation IoT (C-02) se recouvrent | Décider : simulateur seul, ou simulateur calé sur un jeu ouvert ; adapter DAT-01 | Les deux | Ouvert |
| E-05 | Répartition présentée : Manoa porte NoSQL et AWS ; backlog : BE-05 et CLD-09 à CLD-11, CLD-15, CLD-17, CLD-18, CLD-21 sont attribuées à Daddy | Aligner présentation et backlog dans GES-17 | Les deux | Ouvert |