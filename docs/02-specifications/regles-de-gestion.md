# Règles de gestion des données (v1)

Issue : DOC-05. Rédaction : Daddy Luciano. Relecture croisée : Manoa Robel (à faire). Version 1.0 du 27/10/2026.

Une règle de gestion dit **ce que les données ont le droit d'être** et **qui le fait respecter**. Ce document les numérote pour que les [exigences](exigences.md) et les [cas d'échec](parcours.md) puissent s'y référer. Il **ne redéfinit rien** : les définitions, les unités et les valeurs sont dans le [dictionnaire de données](../03-donnees/dictionnaire-de-donnees.md), qui fait foi. En cas de désaccord, le dictionnaire l'emporte et ce document se corrige.

Colonne « Statut » : **Définie** quand une décision écrite la fixe (ADR, dictionnaire, consignes du dépôt) ; **Proposée** quand elle attend la validation du binôme.

Sigles développés une fois : UTC (Coordinated Universal Time, temps universel coordonné), ISO (International Organization for Standardization), SHA-256 (Secure Hash Algorithm, empreinte de 256 bits), TTL (Time To Live, durée de vie), ETL (Extract, Transform, Load).

## 1. Identité et format des données

| ID | Règle | Contrôle | Source | Statut | Exigences |
|---|---|---|---|---|---|
| RG-01 | Un carrefour, un tronçon et un capteur se désignent par un identifiant métier à motif fixe (`INT_01`, `ROAD_001`, `SENSOR_001`). Les clés techniques de l'entrepôt (`*_key`) ne sortent jamais de la base : ni événement, ni API, ni fichier d'échange | Contraintes `CHECK` sur le motif ; schémas JSON des événements | Dictionnaire sections 2 et 4.1 | Définie | EXG-COL-04, EXG-API-02 |
| RG-02 | Toute date et heure est en ISO 8601, en UTC, avec fuseau explicite (`2026-10-20T08:00:10Z`). En base : `timestamptz`. Aucune heure locale n'est stockée | Les schémas refusent une date sans fuseau (DQ-01) ; fuseau de la base fixé à UTC, vérifié le 27/10/2026 | Dictionnaire section 2 | Définie | EXG-COL-02 |
| RG-03 | Chaque grandeur a une unité unique : vitesse en km/h (0 à 200), débit en véhicules par minute, taux d'occupation de 0 à 1 (jamais un pourcentage), longueurs en mètres, durées techniques en secondes (suffixe `_s`) | Contraintes `CHECK` et bornes des schémas | Dictionnaire section 2 | Définie | EXG-COL-02, EXG-TRA-01 |
| RG-04 | Une valeur absente vaut `null`, jamais `0` ni `-1`. Une vitesse n'existe que si au moins un véhicule est passé : route vide, vitesse `null` | `CHECK (average_speed_kmh IS NULL OR vehicle_count > 0)` vérifié le 27/10/2026 | Dictionnaire section 2 | Définie | EXG-TRA-01 |
| RG-05 | Les noms techniques sont en anglais et en `snake_case` ; les libellés affichés à l'usager sont en français | Relecture ; contrat OpenAPI | Dictionnaire section 2 | Définie | EXG-API-02, EXG-NFR-15 |

## 2. Provenance et idempotence

| ID | Règle | Contrôle | Source | Statut | Exigences |
|---|---|---|---|---|---|
| RG-06 | Toute mesure, tout indicateur, toute alerte et tout jeu de données porte sa **provenance** : `SIMULATED`, `REAL_HISTORICAL` ou `REAL_LIVE`, avec `run_id`. Une donnée simulée a aussi `scenario_id` et `seed` | Provenance obligatoire dans les schémas et dans le validateur de `raw_events` ; clé étrangère vers `dim_source` | [ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md) règle 1 | Définie | EXG-NFR-13 |
| RG-07 | Une donnée simulée n'est **jamais** présentée comme réelle : rapports, tableaux et graphiques portent la mention de provenance | Test du tableau de bord ; relecture des rapports | [ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md) règle 3 ; [CLAUDE.md](../../CLAUDE.md) section 6 | Définie | EXG-NFR-13, EXG-TDB-02 |
| RG-08 | Un événement a un `id` unique (`<run_id>:<sensor_id>:<instant en millisecondes>`). Un même `id` reçu deux fois est ignoré et compté | Index unique `uniq_event_id`, vérifié le 27/10/2026 | Dictionnaire section 5 | Définie | EXG-COL-03 |
| RG-09 | Un chargement est **idempotent** : la clé (tronçon, début de fenêtre, taille de fenêtre, run) identifie un fait ; rejouer met à jour la ligne, ne la duplique pas | Clé primaire de `fact_traffic_window`, rejeu vérifié le 27/10/2026 | Dictionnaire section 6 ; [ADR-011](../01-architecture/adr/ADR-011-temps-reel-et-batch.md) | Définie | EXG-TRA-04, EXG-DON-02 |
| RG-10 | Un run est reproductible : mêmes graine et scénario, mêmes événements | Test de rejeu à graine fixe (MS-07) | [ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md) règle 2 | Définie | EXG-COL-01, EXG-IA-02 |

## 3. Calcul des indicateurs et des états

| ID | Règle | Contrôle | Source | Statut | Exigences |
|---|---|---|---|---|---|
| RG-11 | Une fenêtre couvre [début, début + taille[ en **temps d'événement**, alignée sur sa taille ; deux tailles : 60 s et 300 s. Retard autorisé : 30 s ; désordre toléré : 10 s (valeurs de départ, à mesurer) | `CHECK (window_size_s IN (60, 300))` ; tests de MS-09 avec messages en retard | Dictionnaire section 6 ; [ADR-011](../01-architecture/adr/ADR-011-temps-reel-et-batch.md) | Définie (valeurs de départ) | EXG-TRA-01, EXG-TRA-02 |
| RG-12 | La vitesse moyenne d'une fenêtre est pondérée par le nombre de véhicules ; le ratio de vitesse est la vitesse moyenne divisée par la vitesse en circulation fluide du tronçon ; la complétude est le rapport entre mesures reçues et attendues, plafonné à 1 | Colonne `completeness` calculée par la base ; recalcul SQL de référence (MS-10) | Dictionnaire section 6 | Définie | EXG-TRA-01 |
| RG-13 | L'état d'un tronçon prend quatre valeurs ordonnées (`UNKNOWN`, `FREE_FLOW`, `SLOW`, `CONGESTED`), calculées sur des fenêtres de 1 minute avec **hystérésis** : seuils différents à la montée et à la descente, nombre de fenêtres consécutives exigé. Fenêtre vide : fluide. Complétude inférieure à 0,5 : `UNKNOWN` | Tests unitaires du classificateur de référence (IA-01) | Dictionnaire section 7.1 ; [ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md) | Définie (seuils de départ) | EXG-TRA-03 |
| RG-14 | Un épisode s'ouvre quand l'état quitte FREE_FLOW pour SLOW ou CONGESTED et se ferme au retour à FREE_FLOW ; un épisode est unique par (tronçon, run, début) | Contrainte `UNIQUE` de la migration `0002` (créée le 27/10/2026, son refus d'un doublon n'a pas été exercé) | Dictionnaire section 7.2 | Définie | EXG-TRA-03, EXG-ALE-01 |
| RG-15 | Une mesure est classée `VALID`, `PARTIAL` ou `SUSPECT` selon les règles de qualité DQ-01 à DQ-10 ; une mesure `SUSPECT` ne compte pas dans les indicateurs ; tout rejet garde son motif | Tests de MS-08, MS-09 et DAT-04 ; tables `rejects` et `dwh.etl_reject` | Dictionnaire section 8 | Définie | EXG-TRA-02, EXG-DON-03 |

## 4. Alertes

| ID | Règle | Contrôle | Source | Statut | Exigences |
|---|---|---|---|---|---|
| RG-16 | Il y a **une alerte par épisode** : au plus une alerte non résolue par type, tronçon et run | Index unique partiel, vérifié le 27/10/2026 | Dictionnaire section 7.3 ; [ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md) | Définie | EXG-ALE-01 |
| RG-17 | Le cycle de vie est CREATED, NOTIFIED, ACKNOWLEDGED, RESOLVED ; chaque changement écrit une ligne d'historique et un événement dans la boîte d'envoi, **dans la même transaction** | Contraintes de cohérence en base, vérifiées le 27/10/2026 ; test de service (MS-11) pour l'ordre des transitions, que la base ne contrôle pas | Dictionnaire section 7.3 ; [ADR-009](../01-architecture/adr/ADR-009-bus-evenements.md) | Définie | EXG-ALE-02 |
| RG-18 | La cause d'une alerte est `UNKNOWN` tant qu'aucun événement confirmé n'existe. `CONFIRMED_INCIDENT`, `ROADWORKS` et `SPECIAL_EVENT` ne s'attribuent que sur un événement confirmé | Valeur par défaut et liste de causes en base ; test de service | Dictionnaire section 7.3 | Définie | EXG-ALE-03 |
| RG-19 | Deux notifications d'un même tronçon sont espacées d'au moins `min_gap_s` (300 s pour la congestion) | Test de service (MS-11) | Dictionnaire section 7.3 | Définie | EXG-ALE-01 |

## 5. Propriété, droits et sécurité des données

| ID | Règle | Contrôle | Source | Statut | Exigences |
|---|---|---|---|---|---|
| RG-20 | Un service est seul à écrire dans ses schémas et collections. Aucune clé étrangère ne traverse deux services : les liens sont des identifiants textuels. Chaque service a son propre compte de base | 11 cas de droits SQL et 29 cas MongoDB vérifiés le 27/10/2026 ; `db-check` | [ADR-008](../01-architecture/adr/ADR-008-microservices.md) règle 1 ; [bases locales](../03-donnees/base-de-donnees-locale.md) | Définie | EXG-NFR-05, EXG-API-01 |
| RG-21 | Aucun secret (mot de passe, jeton, clé) dans un fichier, une capture, un message de commit ou un journal ; les secrets viennent de `.env`, ignoré par Git. Les mots de passe des bases sont générés au hasard | gitleaks et Snyk en CI ; `scripts/dev/test_secrets.py` | [CLAUDE.md](../../CLAUDE.md) section 6 ; [secrets](../04-devsecops/secrets.md) | Définie | EXG-NFR-11 |
| RG-22 | Chaque appel authentifié et chaque commande de feux laissent une entrée d'audit : qui, quoi, quand, résultat, `correlation_id`. Le journal ne contient ni secret ni donnée personnelle | Collection `audit_logs` et son validateur ; test (BE-05) | Dictionnaire section 10.3 | Définie | EXG-API-03, EXG-REP-04 |
| RG-23 | En v1, aucune donnée personnelle d'usager final n'est stockée : les alertes concernent un tronçon, pas une personne, et le canal de notification est simulé. Les seules données personnelles sont les comptes de l'application (nom d'utilisateur, empreinte du mot de passe, jamais le mot de passe) | Relecture du schéma `app` (BE-02) et du service d'alerte (MS-11) | Contrat [OpenAPI](../../contracts/openapi/README.md), schéma `User` | Proposée : à confirmer avec MS-11 | EXG-API-03, EXG-API-01 |

## 6. Conservation, évolution et jeux de données

| ID | Règle | Contrôle | Source | Statut | Exigences |
|---|---|---|---|---|---|
| RG-24 | Durées de conservation : `raw_events` 14 jours, `rejects` 30 jours, autres données illimitées en local. Purge par index à durée de vie (TTL) | Index `ttl_received_at` et `ttl_rejected_at`, vérifiés le 27/10/2026 ; la suppression effective n'a pas été observée | Dictionnaire section 10 | Définie (valeurs de départ) | EXG-COL-03 |
| RG-25 | Les migrations SQL sont numérotées (`NNNN_description.sql`), appliquées une fois dans l'ordre, et **jamais modifiées** après application : on en ajoute une nouvelle. Les tables du schéma `app` viennent d'Alembic | Empreinte SHA-256 de chaque migration conservée ; seconde passe sans effet, vérifiée le 27/10/2026 | [bases locales](../03-donnees/base-de-donnees-locale.md) section 6 ; [ADR-024](../01-architecture/adr/ADR-024-bases-de-donnees-locales.md) | Définie | EXG-DON-04, EXG-DON-05 |
| RG-26 | L'API est versionnée dans le chemin (`/api/v1`) ; un changement incompatible crée une nouvelle version majeure. Un type d'événement porte sa version majeure (`...v1`) ; un changement incompatible crée un nouveau type | `scripts/dev/test_openapi.py` ; `contracts/tests` | Contrats [OpenAPI](../../contracts/openapi/README.md) ; [contrats](../../contracts/README.md) | Définie | EXG-API-02, EXG-COL-04 |
| RG-27 | Toute erreur de l'API a le même format (`application/problem+json`, code d'erreur stable) | `scripts/dev/test_openapi.py` ; tests de contrat (BE-06) | Contrats [OpenAPI](../../contracts/openapi/README.md) | Définie | EXG-API-02 |
| RG-28 | Le dépôt est public : aucun jeu réel n'y est redistribué, aucun jeu de plus de 1 Mo n'y est versionné. Tout jeu a une fiche de provenance et une empreinte SHA-256. Le découpage entraînement, validation, test se fait par run et par scénario | Fiche de provenance ; test de non-recouvrement des runs (IA-08) | [ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md) règles 4 à 7 ; [CLAUDE.md](../../CLAUDE.md) section 6 | Définie | EXG-IA-02 |
