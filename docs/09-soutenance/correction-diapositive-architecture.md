# Correction de la diapositive d'architecture : MongoDB, pas DynamoDB

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsable : Manoa Robel
Dernière mise à jour : 20/10/2026
Issue de suivi : DOC-10

La diapositive 4 « Architecture de la plateforme » de la présentation « Plan d'action BC05 » citait Amazon DynamoDB comme base non relationnelle. Les décisions d'architecture retiennent MongoDB ([ADR-002](../01-architecture/adr/ADR-002-postgresql-mongodb.md)). La diapositive est corrigée.

Abréviations : ADR (Architecture Decision Record, enregistrement de décision d'architecture), C4 (modèle de diagrammes : contexte, conteneurs, composants), NoSQL (Not Only SQL (Structured Query Language)).

## 1. Modifications de la présentation

Fichier : `Novaria-Core-Plan-action-BC05.pptx` (version du 15/10/2026). La copie corrigée porte le suffixe `-corrige` ; l'original n'est pas modifié. Seules la diapositive 4 et ses notes d'orateur changent ; les 10 autres pages sont identiques (vérifié par comparaison du texte de chaque page).

| Élément | Avant | Après |
|---|---|---|
| Titre de la carte de stockage | Amazon DynamoDB | MongoDB |
| Sous-titre | NoSQL (Not Only SQL) : journaux | NoSQL (Not Only SQL) : journaux et statistiques |
| Texte alternatif de l'icône | Amazon DynamoDB | MongoDB |
| Notes d'orateur | « … et Amazon DynamoDB (journaux). » | « … et MongoDB (journaux et statistiques). » |

L'icône est un cylindre de base de données générique : elle reste.

## 2. Cohérence avec les ADR

Recherche du nom de la base non relationnelle dans `docs/01-architecture/adr/` (20/10/2026) :

| Nom | Occurrences | Contexte |
|---|---|---|
| MongoDB | 85 (19 fichiers, index inclus) | Choix retenu (ADR-002 option C), hébergement ([ADR-022](../01-architecture/adr/ADR-022-hebergement-mongodb.md)), exécution locale ([ADR-024](../01-architecture/adr/ADR-024-bases-de-donnees-locales.md)) |
| DynamoDB | 2 | ADR-002 : option D **écartée** ; ADR-020 : verrou de l'état Terraform, précisé comme « sans lien avec la base non relationnelle du projet » |
| DocumentDB | 1 | ADR-022 : option C écartée |

Les ADR et la présentation citent la même base non relationnelle : MongoDB. Le test `scripts/dev/test_coherence_bases.py` garde ce résultat : DynamoDB et DocumentDB ne peuvent apparaître que dans ces trois endroits.

## 3. Schéma C4

| Point | État |
|---|---|
| Diagrammes C4 | **Non vérifiable** : ils n'existent pas encore (issue DOC-03, ouverte ; le dossier `docs/01-architecture/c4/` est vide) |
| À contrôler à la livraison de DOC-03 | Le conteneur « base non relationnelle » s'appelle MongoDB et porte les journaux d'audit, les statistiques d'usage, les événements bruts et le suivi des modèles ([ADR-002](../01-architecture/adr/ADR-002-postgresql-mongodb.md)) |

## 4. Autres présentations vérifiées

| Fichier | Résultat |
|---|---|
| `Novaria-Core-Strategie-de-developpement-et-plan-daction.pptx` | Aucune mention de DynamoDB ; la base est désignée « base NoSQL » sans nom de produit |

## 5. Ce qu'il reste à faire

- Remplacer la présentation remise au professeur par la copie corrigée, ou la lui renvoyer.
- Contrôler les diagrammes C4 à la livraison de DOC-03 (section 3).
- La diapositive décrit la cible AWS ; l'exécution reste locale (ADR-023). Elle n'a pas été modifiée sur ce point.
