# Registre des risques

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 20/10/2026
Issue de suivi : GES-07

Ce registre consigne chaque risque du projet avec sa cause, son effet, un responsable, une action et un signal de suivi.

## Mode d'emploi

- Un risque = une ligne et un identifiant (R1, R2…). Une ligne n'est jamais supprimée : on change son statut et on note la date et la raison.
- Responsable : Daddy, Manoa ou Les deux. Un risque sans responsable ni action n'est pas accepté.
- Statuts : **Ouvert** (à surveiller), **Suspendu** (cause écartée pour le moment, avec la référence du changement), **Clos** (risque disparu, avec la date).
- Revue à la fin de chaque jalon (M1 à M6) et à chaque changement de périmètre inscrit dans `journal-changements.md`.
- Les références C-xx renvoient au registre des demandes (`registre-des-demandes.md`), les références ADR aux décisions d'architecture (`docs/01-architecture/adr/`).
- Abréviations : ADR (Architecture Decision Record, enregistrement de décision d'architecture), AWS (Amazon Web Services), ETL (Extract, Transform, Load, extraction, transformation, chargement).

## Risques

| ID | Risque | Cause | Effet | Responsable | Action | Signal de suivi | Statut |
|---|---|---|---|---|---|---|---|
| R1 | Neuf compétences à livrer | Référentiel BC05 large | Retard de livraison | Les deux | 3 compétences en prototype ciblé | Écart au planning ProjectLibre | Ouvert |
| R2 | Données urbaines inadaptées | Jeu de données incomplet | Indicateurs non calculables | Daddy | Jeu de données ouvert choisi en semaine 2 | Taux de rejet ETL | Ouvert |
| R3 | Coûts du cloud qui dérivent | Ressources laissées actives | Dépassement du plafond | Manoa | Arrêt après chaque essai, budget AWS à alertes | Alertes AWS Budgets | Suspendu (C-05) : aucune ressource AWS |
| R4 | Modèle sans valeur démontrée | Signal faible dans les données | Prévision inutile | Manoa | Comparaison à une référence simple | Métrique vs référence | Ouvert |
| R5 | Cahier des charges qui évolue | Nouvelles demandes | Dérive de périmètre | Daddy | Tri inclus / exclu / à arbitrer | Journal des changements | Ouvert |
| R6 | Écart entre l'exécution locale et la cible AWS | Aucun service AWS n'est exécuté | Surprise si AWS est autorisé plus tard (versions, droits, réseau) | Daddy | Table d'équivalences et adaptateurs (ADR-025) ; versions épinglées ; relecture à chaque jalon (DOC-11) | Écarts consignés dans la table | Ouvert |
| R7 | Instruction du professeur donnée oralement | Aucune trace écrite de la consigne « localhost, pas AWS » | Contestation à la soutenance, périmètre contesté | Manoa | Demander une confirmation écrite ; ligne dans les registres | Réponse écrite reçue ou non | Ouvert |
| R8 | Postes Windows et Linux qui divergent | Deux systèmes, commandes et fins de ligne différentes | « Ça marche chez moi », temps perdu | Les deux | Docker, `dev.py`, documentation à deux colonnes (ADR-026) ; premier démarrage de Daddy consigné | Résultat de `db-check` sur chaque poste | Ouvert |
| R9 | Données simulées prises pour des données réelles, ou modèle qui apprend le simulateur | Absence de données réelles avec comptages | Conclusions trompeuses devant le jury | Manoa | Provenance obligatoire, label = vérité terrain, découpage par run, limite écrite dans le rapport (ADR-027) | Fiche de provenance présente pour chaque jeu | Ouvert |

## Origine des risques

| Risques | Origine | Remarque |
|---|---|---|
| R1 à R5 | Les cinq risques de la présentation « Novaria Core : socle d'UrbanHub », reportés à l'ouverture du registre | [À VÉRIFIER : concordance avec la diapositive des risques ; le fichier de la présentation n'est pas dans le dépôt] |
| R6 à R9 | Ajoutés le 20/10/2026 avec l'exécution locale d'abord (C-05 à C-07) | Voir `journal-changements.md` |
