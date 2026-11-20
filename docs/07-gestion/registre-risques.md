# Registre des risques

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 20/11/2026
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
| R10 | Failles de sécurité sans correctif dans les images de base | Correctif amont non publié (Debian 13, image python:3.15-slim) | Contrôle Snyk bloquant ou, si une exception est acceptée, faille connue maintenue en service | Manoa | Exceptions datées dans `.snyk` (30 jours au plus, expiration avant le 10/12/2026), reconstruction des images avant l'expiration, scan hebdomadaire de `main` (politique : `docs/04-devsecops/exceptions.md`) | Date d'expiration des exceptions ; résultat du scan hebdomadaire | Ouvert : 6 exceptions actives. SNYK-DEBIAN13-ATTR-17678182 et SNYK-DEBIAN13-ACL-17677866, créées le 2026-10-17 et renouvelées le 2026-11-15, expiration 2026-12-09 (revue du 15/11/2026 : toujours aucun correctif publié, `exceptions.md` section 14). SNYK-DEBIAN13-ZLIB-19520500 (zlib1g) : fermée le 2026-11-15, corrigée par `1:1.3.dfsg+really1.3.1-1+deb13u1` (`exceptions.md` section 14). SNYK-DEBIAN13-SQLITE3-22119065, SNYK-DEBIAN13-SQLITE3-22119091 et SNYK-DEBIAN13-SQLITE3-22119098 (libsqlite3-0), créées le 2026-11-03, expiration 2026-12-03 (`exceptions.md` section 12). SNYK-DEBIAN13-ZLIB-22249554 (zlib1g), créée le 2026-11-05, expiration 2026-12-05 (`exceptions.md` section 13) |
| R11 | Complexité d'exploitation de l'architecture en quatre services | Quatre services, passerelle, bus, deux bases et simulateur à démarrer et déboguer sur deux postes | Temps perdu en environnement, parcours de bout en bout instable, monolithe distribué par appels synchrones | Les deux | Gabarit de service (MS-04), Compose unique (MS-06), lanceur `dev.py`, journaux corrélés (MS-16), tests de bout en bout (MS-15) ; règle « pas d'appel synchrone entre services » vérifiée en revue (ADR-008) | `docker compose up` ne démarre pas l'ensemble sur l'un des deux postes | Ouvert |
| R12 | Parcours de bout en bout en microservices non atteint avant le 10/12/2026 | Charge cumulée supérieure à la capacité de deux personnes (durées du planning déjà au-dessus de cette capacité) | Soutenance sans démonstration complète | Les deux | Point de décision le 15/11/2026 avec bascule vers le monolithe modulaire ; ordre d'abandon : prototypes P1, Flink au profit d'un consommateur Python (ADR-008, ADR-011) | Parcours capteur, collecte, traitement, alerte, réponse non opérationnel en local au 15/11/2026 | Ouvert |
| R13 | Première surface publique sans jeton (application citoyenne, C-08) : fuite d'un champ interne ou abus de débit | Des routes lisibles par tout le monde, servies par des services qui détiennent des données internes (noms d'opérateurs, capteurs, comptages) | Donnée interne ou personnelle exposée ; routes saturées | Daddy | DTO à liste blanche et test d'égalité des champs, zone de débit dédiée, routes générées depuis les contrats, matrice d'accès étendue ([ADR-030](../01-architecture/adr/ADR-030-application-citoyenne-perimetre-et-acces.md), CIT-02, CIT-06) | Test des champs publics ; sortie de `dev.py acces` pour les routes publiques | Ouvert |
| R14 | Partie citoyenne ajoutée tard : le jalon M6 se termine le 08/12/2026, deux jours avant la soutenance | Demande C-08 inscrite le 20/11/2026, huit issues CIT et trois issues SIT sur deux personnes | Application citoyenne ou site de présentation inachevés ; parcours de bout en bout non repassé | Les deux | Périmètre minimal décidé par l'ADR-030 (lecture seule, sans compte, aucun nouveau service) ; repli sur des instantanés générés (ADR-030, section 6) ; ordre d'abandon : suivi d'un tronçon, puis alertes, avant l'état par tronçon | Nombre d'issues CIT fermées au 01/12/2026 (`dev.py tableau-de-bord`) | Ouvert |

## Origine des risques

| Risques | Origine | Remarque |
|---|---|---|
| R1 à R5 | Les cinq risques de la présentation « Novaria Core : socle d'UrbanHub », reportés à l'ouverture du registre | [À VÉRIFIER : concordance avec la diapositive des risques ; le fichier de la présentation n'est pas dans le dépôt] |
| R11 et R12 | Ajoutés le 27/10/2026 avec la révision de l'ADR-008 (MS-01) : complexité d'exploitation et délai du 10/12/2026 | Voir `docs/01-architecture/adr/ADR-008-microservices.md`, section 5 |
| R13 et R14 | Ajoutés le 20/11/2026 avec la demande C-08 (application citoyenne, CIT-01) : surface publique et délai de M6 | Voir `docs/01-architecture/adr/ADR-030-application-citoyenne-perimetre-et-acces.md`, section 5 |
| R6 à R10 | Ajoutés le 20/10/2026 : R6 à R9 avec l'exécution locale d'abord (C-05 à C-07), R10 avec la politique de vulnérabilités (CLD-23) | Voir `journal-changements.md` ; toute faille sans correctif est notée en R10 |
