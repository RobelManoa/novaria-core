# Exigences de Novaria Core (v1)

Issue : DOC-05. Rédaction : Daddy Luciano. Relecture croisée : Manoa Robel (à faire). Version 1.0 du 27/10/2026.

Statut : **brouillon pour relecture**. Les exigences viennent des décisions d'architecture (ADR), du [registre des demandes](../07-gestion/registre-des-demandes.md), de la [note de cadrage](../00-cadrage/note-de-cadrage.md) et des critères d'acceptation du backlog. La validation par le professeur du cahier des charges fonctionnel (point 5 de GES-06) reste **à consigner** dans [decisions-professeur.md](../07-gestion/decisions-professeur.md). Les valeurs chiffrées marquées « valeur de départ » ou « proposé » sont des hypothèses à mesurer, pas des engagements.

Ce fichier répond à la question « que doit faire le système, et comment le prouve-t-on ? ». Les parcours et les cas d'échec sont dans [parcours.md](parcours.md), les règles sur les données dans [regles-de-gestion.md](regles-de-gestion.md), l'interface REST (Representational State Transfer) dans [openapi.yaml](openapi.yaml).

## Comment lire

Chaque exigence a un identifiant `EXG-<domaine>-<numéro>`, un **contexte** (pourquoi), un **critère mesurable** (comment on dit qu'elle est tenue), une **priorité**, une **preuve attendue** (le fichier, le test ou la capture qui la démontre) et un **état** constaté à la date du document.

| Priorité | Sens |
|---|---|
| **Doit** | Sans elle, la démonstration de bout en bout échoue ou une règle de la note de cadrage n'est pas tenue |
| **Devrait** | Importante ; un repli connu existe si le temps manque |
| **Pourrait** | Utile ; abandonnée en premier si le planning glisse |

| État | Sens |
|---|---|
| **Prouvé** | La preuve attendue existe et a été exécutée |
| **Partiel** | Une partie existe (contrat, schéma de base, squelette, procédure), le reste est à construire ; la cellule dit laquelle |
| **À faire** | Rien d'exécutable n'existe encore |

Les domaines : COL (collecte et simulation), TRA (traitement et entrepôt), ALE (alertes), REP (réponse extérieure, feux), API (interface et sécurité), TDB (tableau de bord), DON (données décisionnelles et ETL (Extract, Transform, Load)), IA (intelligence artificielle), NFR (exigences non fonctionnelles : performance, exploitation, sécurité).

Sigles employés ci-dessous, développés une fois : p95 (95e centile : 95 % des mesures sont au moins aussi rapides), SHA-256 (Secure Hash Algorithm, empreinte de 256 bits), SQL (Structured Query Language), UTC (Coordinated Universal Time), CI (Continuous Integration, intégration continue), TTL (Time To Live, durée de vie), MAE (Mean Absolute Error, erreur absolue moyenne), F1 macro (moyenne, sur les classes, de la mesure F1 qui combine précision et rappel), RPA (Robotic Process Automation, automatisation des tâches), SSE (Server-Sent Events, flux d'événements du serveur vers le navigateur).

## 1. Collecte et simulation

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-COL-01 | **Simulateur reproductible.** Sans données de référence, on ne peut ni tester ni entraîner ([ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md)) | Deux runs de même scénario et de même graine produisent des mesures identiques (même empreinte SHA-256 du flux). Les 5 scénarios minimaux (journée calme, pointe du matin, incident ponctuel, capteur muet, messages en retard ou en double) se lancent à la demande | Doit | `simulator/README.md` et test de rejeu à graine fixe | À faire | MS-07 |
| EXG-COL-02 | **Validation à l'entrée.** Un message hors contrat ne doit jamais atteindre le traitement ([ADR-012](../01-architecture/adr/ADR-012-validation-contrats-zod.md)) | Sur un jeu de test mêlant messages valides, invalides et doublons : 100 % des valides arrivent sur `iot.raw`, 100 % des invalides sur `errors.dlq` avec un motif, 0 doublon publié | Doit | Test d'intégration et `docs/03-donnees/collecte.md` | Partiel : schéma de la mesure et cas invalides testés dans `contracts/tests` ; service absent | MS-08, MS-03 |
| EXG-COL-03 | **Stock brut rejouable.** Rejouer l'historique et prouver un calcul exigent de garder les mesures reçues ([ADR-011](../01-architecture/adr/ADR-011-temps-reel-et-batch.md)) | Chaque message accepté figure dans `raw_events` avec `received_at` ; un second message de même `id` est refusé par l'index unique ; la purge à 14 jours est configurée | Doit | Test d'intégration et capture MongoDB | Partiel : collection, validateur, index unique et durée de vie créés et vérifiés sous Windows le 27/10/2026 ; service absent | MS-08 |
| EXG-COL-04 | **Un contrat par sujet.** Un service ne lit que ce qu'un schéma décrit ([ADR-012](../01-architecture/adr/ADR-012-validation-contrats-zod.md)) | Les 6 sujets Kafka ont un schéma ; chaque exemple valide passe et chaque cas invalide est refusé pour la bonne raison ; un service dont un message viole le contrat fait échouer son test | Doit | `contracts/events/` et `contracts/tests/` | Partiel : 3 sujets sur 6 couverts (`iot.raw`, `traffic.indicators`, `alerts.events`) | MS-03 |

## 2. Traitement et entrepôt

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-TRA-01 | **Indicateurs par fenêtre.** Le tronçon est l'unité d'analyse ; fenêtres de 1 et 5 minutes en temps d'événement ([ADR-011](../01-architecture/adr/ADR-011-temps-reel-et-batch.md), [dictionnaire](../03-donnees/dictionnaire-de-donnees.md) section 6) | Sur un jeu de test, chaque indicateur publié (débit, vitesse moyenne pondérée, ratio de vitesse, complétude) est égal à un recalcul SQL de référence | Doit | `services/traitement/tests/` | Partiel : table `dwh.fact_traffic_window`, ses contraintes et le contrat d'indicateur vérifiés ; service absent | MS-09, MS-10 |
| EXG-TRA-02 | **Retards, doublons et valeurs douteuses tracés.** Un chiffre faux sans trace est pire qu'un rejet | Un message en retard au-delà de 30 s (valeur de départ) est rejeté avec le motif `LATE` ; une mesure `SUSPECT` est exclue des indicateurs ; chaque cas est compté dans `processing_stats` | Doit | `docs/03-donnees/flux.md` et test avec le simulateur d'anomalies | À faire | MS-09 |
| EXG-TRA-03 | **État de congestion stable.** L'usager ne doit pas recevoir une alerte qui clignote ([ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md)) | Le tableau de transitions du dictionnaire (section 7.1) est appliqué ; une série de ratios qui oscille autour d'un seuil produit au plus une transition ; une fenêtre de complétude inférieure à 0,5 donne `UNKNOWN` | Doit | Tests unitaires du classificateur de référence | À faire | IA-01, MS-09 |
| EXG-TRA-04 | **Entrepôt rejouable.** Rejouer un chargement ne doit ni dupliquer ni changer les totaux ([ADR-013](../01-architecture/adr/ADR-013-integration-donnees.md)) | Deux chargements successifs du même jeu laissent identiques les totaux de `fact_traffic_window` ; un fait déjà présent est mis à jour, pas dupliqué | Doit | Test de double chargement sur base vide | Partiel : clé d'idempotence et mise à jour d'un fait vérifiées en SQL le 27/10/2026 ; chargeur absent | DAT-05 |
| EXG-TRA-05 | **Flux et rejeu cohérents.** Le même code doit donner le même résultat en direct et par lots ([ADR-011](../01-architecture/adr/ADR-011-temps-reel-et-batch.md)) | Chaque nuit, l'écart entre les indicateurs du flux et le recalcul par lots est nul ou expliqué, et tracé | Devrait | Rapport du contrôle de cohérence | À faire | MS-09 |

## 3. Alertes

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-ALE-01 | **Une alerte par épisode.** Une alerte par mesure noierait l'usager ([ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md)) | Une congestion simulée crée une seule alerte (au plus une non résolue par type, tronçon et run) ; elle est résolue automatiquement (`AUTO`) au retour à l'état fluide | Doit | Test d'intégration et capture | Partiel : index d'unicité partiel vérifié en base le 27/10/2026 ; service absent | MS-11 |
| EXG-ALE-02 | **Cycle de vie complet.** L'opérateur doit pouvoir accuser réception et clore | L'alerte passe par CREATED, NOTIFIED, ACKNOWLEDGED, RESOLVED ; chaque transition écrit `alert_history` et `outbox_event` dans la même transaction ; accuser réception deux fois ou clore une alerte résolue renvoie 409 | Doit | Test de service et test de contrat sur `acknowledge` et `resolve` | Partiel : tables, contraintes et contrat d'API vérifiés ; service absent | MS-11, BE-06 |
| EXG-ALE-03 | **Cause non affirmée.** Une baisse de vitesse ne prouve pas un accident ([ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md)) | 100 % des alertes issues de la règle de congestion ont `cause = UNKNOWN` tant qu'aucun événement confirmé n'existe | Doit | Test de service et contrainte `DEFAULT 'UNKNOWN'` | Partiel : valeur par défaut et liste des causes vérifiées en base | MS-11 |
| EXG-ALE-04 | **Défaut de capteur distinct d'une congestion.** Un capteur muet ne doit pas passer pour une route arrêtée | Un capteur sans mesure pendant plus de 60 s déclenche une alerte `SENSOR_FAULT` (règle `capteur.muet`) et non une alerte de congestion | Devrait | Test avec le scénario « capteur muet » | À faire | MS-11, MS-07 |

## 4. Réponse extérieure (feux de circulation)

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-REP-01 | **Recommandation déterministe.** Un modèle ne commande jamais seul ([ADR-015](../01-architecture/adr/ADR-015-modeles-ia.md)) | Pour un jeu d'entrées fixé, la recommandation de phases est égale au calcul de référence (formule de Webster) ; le score d'un modèle n'est qu'une entrée de ce calcul | Doit | `services/traitement/tests/` | À faire | MS-10 |
| EXG-REP-02 | **Garde-fous de commande.** Une commande dangereuse n'atteint jamais le contrôleur ([ADR-008](../01-architecture/adr/ADR-008-microservices.md), règle 6) | La liste des règles de sécurité est écrite avant le code (durée minimale et maximale d'une phase, phases conflictuelles interdites : propositions à valider) ; pour chaque règle, une commande qui la viole est refusée (`UNSAFE_COMMAND`) et le refus est journalisé | Doit | `services/reponse/tests/` et liste des règles | Partiel : code `UNSAFE_COMMAND` décrit dans le contrat ; règles et service absents | MS-12 |
| EXG-REP-03 | **Mode dégradé.** Sans recommandation, les feux gardent un comportement sûr | Quand aucune recommandation n'arrive pendant le délai fixé (à définir, voir [README](README.md), points ouverts), le contrôleur revient au plan fixe ; le retour à la normale se fait à la recommandation suivante | Doit | `services/reponse/tests/` avec coupure simulée | À faire | MS-12 |
| EXG-REP-04 | **Commande manuelle.** L'opérateur garde la main | Une commande saisie au tableau de bord passe par les mêmes garde-fous, est appliquée si elle est sûre, et est journalisée dans `audit_logs` avec l'opérateur ; une seconde commande pendant la première est refusée (409) | Doit | Test de bout en bout et capture | Partiel : route `POST /signals/{id}/commands` décrite dans le contrat | MS-14, MS-12 |

## 5. Interface, sécurité et audit

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-API-01 | **Authentification et rôles.** Seul un utilisateur connu agit, selon son rôle ([openapi.yaml](openapi.yaml)) | Sans jeton valide : 401. Avec un rôle insuffisant : 403. Trois rôles `viewer`, `operator`, `admin` (proposition à valider). Seules `/health` et `/auth/login` sont publiques | Doit | Tests de `services/traitement/tests/contract/` | Partiel : rôles et sécurité décrits dans le contrat et contrôlés par `scripts/dev/test_openapi.py` | BE-03, MS-13 |
| EXG-API-02 | **Conformité au contrat.** Le contrat est la source de vérité | Chaque réponse, succès comme erreur, respecte `openapi.yaml` ; chaque erreur documentée est testée ; le format d'erreur est `application/problem+json` | Doit | Tests de contrat | Partiel : contrat chargé et 15 tests de structure ; seule la route `/health` est implémentée | BE-04, BE-06 |
| EXG-API-03 | **Audit et usage.** Savoir qui a fait quoi | Chaque appel authentifié produit une entrée `audit_logs` (acteur, action, résultat, `correlation_id`) sans secret ni donnée personnelle ; les compteurs `usage_stats` s'incrémentent | Devrait | Test et capture MongoDB | Partiel : collections, validateurs et droits vérifiés le 27/10/2026 ; code absent | BE-05 |

## 6. Tableau de bord

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-TDB-01 | **Connexion et routes protégées** | Une route protégée est inaccessible sans connexion (renvoi vers la page de connexion) ; un jeton expiré renvoie à la connexion | Doit | Test du front-end | À faire | FE-03 |
| EXG-TDB-02 | **Indicateurs fidèles.** Afficher ce que dit l'API | Sur un jeu de test, les valeurs affichées (vitesse, débit, état) sont égales à celles de l'API | Doit | Captures et test | À faire | FE-04, BE-04 |
| EXG-TDB-03 | **Alertes et feux en direct** | Une alerte créée apparaît sans rechargement dans le délai de EXG-NFR-03 ; l'état des feux est visible ; les données viennent des services, jamais de valeurs écrites en dur | Doit | Test de bout en bout et capture | À faire | MS-14 |
| EXG-TDB-04 | **Page des prévisions** | La page affiche la prévision renvoyée par l'API, avec son horizon et sa provenance | Devrait | Captures de la page | À faire : page provisoire du socle (FE-01) | FE-05 |
| EXG-TDB-05 | **Page des rapports automatiques** | Un rapport produit par le robot apparaît dans la liste | Devrait | Captures de la page | À faire : page provisoire du socle (FE-01) | FE-06 |

## 7. Données décisionnelles et ETL

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-DON-01 | **Indicateurs décisionnels définis.** Un indicateur sans définition écrite n'est pas défendable ([ADR-014](../01-architecture/adr/ADR-014-architecture-decisionnelle.md)) | Chaque indicateur a une définition, une source, un calcul et une limite connue ; il se recalcule à partir de sa source annoncée ; sa valeur au tableau de bord égale celle de l'API | Doit | `data/dwh/sql/kpi/` et `docs/03-donnees/kpi.md` | À faire | DAT-07 |
| EXG-DON-02 | **Ingestion idempotente** | Le script d'ingestion exécuté deux fois ne crée aucun doublon | Doit | `data/etl/pipelines/` et test | À faire | DAT-03 |
| EXG-DON-03 | **Qualité et rejets tracés** | Chaque règle de qualité a un test ; chaque ligne refusée est écrite dans `dwh.etl_reject` avec sa règle et son motif ; le taux de rejet est journalisé | Doit | `data/etl/transforms/` | Partiel : table `etl_reject` créée, règles DQ-01 à DQ-10 décrites | DAT-04 |
| EXG-DON-04 | **Dictionnaire de données complet.** Il fait foi pour les bases, les événements et les modèles | Chaque table, colonne, collection, champ et index créés par les scripts figure au dictionnaire ; le test échoue sinon | Doit | `scripts/dev/test_dictionnaire.py` | Prouvé : 11 tests, 4 défauts introduits volontairement détectés (27/10/2026) | DAT-02, DAT-10 |
| EXG-DON-05 | **Schéma métier migrable.** Le schéma `app` (utilisateurs, rôles) appartient à l'API métier ([ADR-024](../01-architecture/adr/ADR-024-bases-de-donnees-locales.md)) | `alembic upgrade head` crée le schéma sur une base vide ; les colonnes créées sont ajoutées au dictionnaire | Doit | `services/traitement/migrations/` | Partiel : schéma `app` créé vide à l'initialisation ; aucune révision Alembic | BE-02 |

## 8. Intelligence artificielle

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-IA-01 | **Cadrage avant entraînement** ([ADR-015](../01-architecture/adr/ADR-015-modeles-ia.md)) | `cadrage-ml.md` fixe la cible, la métrique, le seuil d'acceptation et les seuils d'hystérésis ; son commit précède celui du premier entraînement | Doit | `docs/06-ia-mlops/cadrage-ml.md` | À faire | IA-01 |
| EXG-IA-02 | **Jeu d'entraînement reproductible et honnête** ([ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md)) | Le jeu v1 se régénère à l'identique (même empreinte SHA-256) ; le découpage entraînement, validation, test se fait par run et par scénario ; un test échoue si un run figure dans deux parties | Doit | Fiche de provenance dans `data/datasets/` et `ml/tests/` | À faire | IA-02, IA-08 |
| EXG-IA-03 | **Détection de congestion** : le modèle ne vaut que s'il bat la règle simple | Le modèle retenu bat la règle de seuils sur le F1 macro et sur le rappel de la classe CONGESTED, au seuil fixé avant l'entraînement, ou l'écart est documenté ; le délai de détection et les fausses alertes par tronçon et par jour sont mesurés | Doit | `ml/evaluation/` | À faire | IA-03 |
| EXG-IA-04 | **Enregistrement conditionné** ([ADR-017](../01-architecture/adr/ADR-017-mlops-mlsecops.md)) | Un modèle sous le seuil n'entre pas au registre ; un modèle enregistré a son document `model_runs` (version du code, empreinte du jeu, graine, métriques) | Doit | Lien d'exécution du pipeline | Partiel : collection `model_runs` et ses validateurs vérifiés le 27/10/2026 | IA-04, IA-05 |
| EXG-IA-05 | **Dérive surveillée** | Une dérive simulée (vitesses décalées par rapport au jeu d'entraînement) déclenche l'alarme | Devrait | Test sur données décalées | À faire | IA-06 |
| EXG-IA-06 | **Anomalies de capteur** (critère proposé, à confirmer dans IA-09) | Chaque anomalie injectée par le simulateur est détectée par la règle robuste ; la comparaison avec Isolation Forest est consignée | Devrait | `ml/evaluation/` | À faire | IA-09 |
| EXG-IA-07 | **Prévision de vitesse** | Sur METR-LA, le modèle retenu bat la persistance et la moyenne glissante en MAE aux horizons 5, 15 et 30 minutes, ou l'écart est documenté ; il est aussi testé sur un run simulé | Devrait | `ml/evaluation/` | À faire | IA-10 |
| EXG-IA-08 | **Rapport hebdomadaire par robot** | Un rapport d'indicateurs est produit sans intervention manuelle | Devrait | `automation/rpa/` | À faire | IA-07 |

## 9. Exigences non fonctionnelles

| ID | Exigence et contexte | Critère mesurable | Priorité | Preuve attendue | État | Issues |
|---|---|---|---|---|---|---|
| EXG-NFR-01 | **Latence capteur vers bus** ([ADR-011](../01-architecture/adr/ADR-011-temps-reel-et-batch.md), objectif proposé) | Délai entre l'émission d'une mesure et sa présence sur `iot.raw` inférieur ou égal à 1 s au p95 | Devrait | Rapport de mesure du test de bout en bout | À faire | MS-15, MS-08 |
| EXG-NFR-02 | **Latence de fenêtre** (objectif proposé) | Délai entre la fermeture d'une fenêtre et la publication de l'indicateur inférieur ou égal à 2 s | Devrait | Rapport de mesure | À faire | MS-15, MS-09 |
| EXG-NFR-03 | **Délai jusqu'à l'alerte visible.** Ce délai est mesuré et publié ; l'objectif proposé est 10 s au p95, hors délai de la fenêtre | Le rapport donne le p95 du délai entre la mesure déclenchante et l'affichage de l'alerte, avec la méthode de mesure | Doit | Rapport de mesure | À faire | MS-11, MS-15 |
| EXG-NFR-04 | **Débit soutenu** (objectif proposé) | En local, le système absorbe au moins 10 fois le débit nominal du simulateur sans perte de message | Devrait | Rapport de mesure à plusieurs débits | À faire | MS-15, MS-07 |
| EXG-NFR-05 | **Isolation des pannes** ([ADR-008](../01-architecture/adr/ADR-008-microservices.md)) | Quand le service d'alerte est arrêté, la collecte et la réponse extérieure continuent ; à son redémarrage, il rattrape son retard sans perte ni doublon | Doit | Test de bout en bout avec coupure | À faire | MS-15 |
| EXG-NFR-06 | **Observabilité** | Chaque service répond sur `/health` ; à partir d'un `correlation_id`, on retrouve les journaux de tous les services traversés | Devrait | Capture et test | Partiel : `/health` du back-end existe | MS-16, MS-06 |
| EXG-NFR-07 | **Démarrage local complet** ([ADR-023](../01-architecture/adr/ADR-023-execution-locale-d-abord.md)) | `docker compose up --build` (ou `dev.py up`) démarre l'ensemble sur les deux postes et chaque `/health` répond | Doit | Capture de `docker compose ps` | Partiel : bases, bus, back-end et front-end existent ; services métier absents | MS-06, CLD-07 |
| EXG-NFR-08 | **Windows et Linux** ([ADR-026](../01-architecture/adr/ADR-026-postes-de-travail-windows-et-linux.md)) | Chaque commande documentée existe en variante bash et PowerShell ; `db-up` puis `db-check` passent sur les deux postes | Doit | Sorties de `db-check` sur chaque poste | Partiel : bases créées et vérifiées sous Windows le 27/10/2026 ; `db-check` de Compose non relancé | LOC-01, LOC-02 |
| EXG-NFR-09 | **Exécution locale, sans AWS** ([ADR-023](../01-architecture/adr/ADR-023-execution-locale-d-abord.md)) | Aucune ressource AWS (Amazon Web Services) n'est créée ; aucun SDK (Software Development Kit) AWS n'est importé dans le code des services | Doit | Test d'absence de SDK AWS | À faire | LOC-05 |
| EXG-NFR-10 | **Qualité du code** ([ADR-005](../01-architecture/adr/ADR-005-sonarqube-snyk-controles-bloquants.md)) | Lint, tests et build sont verts ; le Quality Gate (seuil de qualité) de SonarQube Cloud passe ; un test en échec bloque la fusion | Doit | Lien d'une exécution verte de la CI | Partiel : workflow `ci.yml` présent, exécution non vérifiée ici | CLD-03, CLD-04, CLD-08, BE-07 |
| EXG-NFR-11 | **Aucun secret exposé** | Aucun secret en clair dans le dépôt, les variables ou les journaux | Doit | Résultats de gitleaks et Snyk ; `scripts/dev/test_secrets.py` | Partiel : test local présent ; contrôles de la CI non vérifiés ici | BE-08, CLD-06 |
| EXG-NFR-12 | **Sauvegarde et restauration** | Après restauration, les données sont utilisables et les totaux identiques | Doit | `docs/08-exploitation/restauration.md` | Partiel : procédure documentée dans `sauvegarde-restauration-locale.md`, non rejouée ici | CLD-15, LOC-03 |
| EXG-NFR-13 | **Provenance visible** ([ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md)) | Tout enregistrement (mesure, indicateur, alerte, jeu) porte `source_type` ; le tableau de bord signale les données simulées ; 0 enregistrement sans provenance | Doit | Tests de contrat et capture | Partiel : champ obligatoire dans les contrats et les validateurs | MS-14, MS-08 |
| EXG-NFR-14 | **Extensibilité vers UrbanHub** ([registre](../07-gestion/registre-des-demandes.md), R-18) | Un nouveau domaine s'ajoute depuis le gabarit de service sans modifier le code d'un service existant | Devrait | Service créé depuis le gabarit, CI verte | À faire | MS-04 |
| EXG-NFR-15 | **Accessibilité et français** | Aucune erreur bloquante à l'audit d'accessibilité ; tous les textes affichés sont en français | Pourrait | Rapport d'audit | À faire | FE-07 |

## Bilan à la date du document

Ces chiffres sont contrôlés par `scripts/dev/test_specifications.py` : il échoue s'ils ne correspondent plus au tableau.

| Mesure | Valeur |
|---|---|
| Exigences | 53 |
| Doit / Devrait / Pourrait | 38 / 14 / 1 |
| Prouvé / Partiel / À faire | 1 / 23 / 29 |

Lecture : la plupart des exigences sont « Doit » parce qu'elles reprennent les critères d'acceptation de tâches P0 du backlog ; ce qui se discute, ce sont les 14 « Devrait » et le « Pourrait », à abandonner en premier si le planning glisse. Le socle de données (bases, contrats d'événements, contrat d'API) est avancé ; **aucun des quatre services métier ni le simulateur n'existe encore**. C'est le gros du travail des jalons M2 et M3.
