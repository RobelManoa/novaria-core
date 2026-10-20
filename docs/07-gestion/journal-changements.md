# Journal des changements de périmètre

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 20/10/2026
Issue de suivi : GES-07

Ce journal consigne, dans l'ordre des dates, chaque changement de périmètre : ce qui est demandé, la décision, son impact et qui a décidé.

## Mode d'emploi

- Chaque demande du registre des demandes (`registre-des-demandes.md`, section 3) a une ligne ici, sous le même identifiant C-xx. Une ligne n'est jamais supprimée ni réécrite : une décision nouvelle ajoute une ligne.
- Décision : **Incluse**, **Exclue** ou **Arbitrée** (avec l'arbitrage).
- Chaque changement qui crée ou modifie un risque est aussi reporté dans `registre-risques.md`.
- Abréviations : AWS (Amazon Web Services), IoT (Internet of Things, internet des objets), LOC (issues d'exécution locale), SUMO (Simulation of Urban MObility), UCI (University of California, Irvine).

## Changements

| Date | Demande | Décision (incluse, exclue, arbitrée) | Impact (lots, ressources, critères) | Décideur |
|---|---|---|---|---|
| 17/10/2026 | C-01 : construire Novaria Core en microservices depuis zéro (collecte, traitement, alerte usager, réponse extérieure) | Incluse (validation du professeur à demander : la topologie présentée décrit un seul back-end) | Issues MS-01 à MS-17 ; les deux membres, jalons M1 à M4 | Binôme |
| 17/10/2026 | C-02 : service de collecte alimenté par des données IoT simulées | Incluse (validation du professeur à demander) | Issues MS-07 et MS-08 ; données, jalon M2 | Binôme |
| 17/10/2026 | C-03 : service d'alerte usager, alertes consultables sur le tableau de bord | Incluse (validation du professeur à demander) | Issues MS-11 et MS-14 ; back-end et front-end, jalons M2 et M3 | Binôme |
| 17/10/2026 | C-04 : service de réponse extérieure (gestion des feux de circulation) | Incluse (validation du professeur à demander) | Issue MS-12 ; back-end, jalon M2 | Binôme |
| 20/10/2026 | C-05 : exécution sur `localhost`, pas sur les services AWS | Incluse (instruction orale du professeur, confirmation écrite à obtenir) | Issues AWS différées ou réorientées (voir ADR-023) ; 6 issues LOC ajoutées ; documents AWS conservés ; planning recalculé | Professeur (oral), binôme |
| 20/10/2026 | C-06 : congestion avant prévision ; label = vérité terrain du simulateur | Incluse | ADR-015 réécrite ; IA-08, IA-09 ajoutées ; IA-01 et IA-03 modifiées | Binôme |
| 20/10/2026 | C-07 : générateur Python v0, SUMO conditionnel, METR-LA pour la prévision, UCI pour le tutoriel | Incluse | ADR-027 ; IA-08, IA-10, IA-11, DAT-10 ajoutées | Binôme |
