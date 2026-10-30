# API des indicateurs : lecture depuis l'entrepôt (BE-04)

> Issue #64. Critère : **les réponses respectent le contrat OpenAPI.** Preuve : les tests de
> [`services/traitement/tests/contract/test_indicators_contract.py`](../../services/traitement/tests/contract/test_indicators_contract.py).
> Contrat : [`traitement.openapi.yaml`](../../contracts/openapi/traitement.openapi.yaml), opérations `listIndicators`, `getIndicator` et `listLatestIndicators`.
> Authentification et rôles : [authentification](../02-specifications/authentification.md) (rôle `viewer` au moins).

## 1. Les trois routes

| Route | Rend | Décrite par |
|---|---|---|
| `GET /api/v1/indicators` | Une page d'indicateurs, du plus récent au plus ancien | `listIndicators` |
| `GET /api/v1/indicators/{indicator_id}` | Un indicateur | `getIndicator` |
| `GET /api/v1/indicators/latest` | La dernière fenêtre d'une minute de **chaque tronçon**, pour le tableau de bord | `listLatestIndicators` |

Un indicateur = un tronçon, une fenêtre de 1 ou 5 minutes, une exécution (`run`). Lecture seule, sur la vue `dwh.v_indicator` (migration `0007`), jamais sur les tables d'écriture ([ADR-014](../01-architecture/adr/ADR-014-architecture-decisionnelle.md), section 4.3).
La connexion à l'entrepôt est ouverte **en lecture seule** (`default_transaction_read_only=on`) : PostgreSQL refuse toute écriture sur elle, même par erreur de code (un test le vérifie).

## 2. Filtres de période et de zone

| Paramètre | Sens | Forme admise |
|---|---|---|
| `from` | Début de période **inclus** (`window_start >= from`) | Date UTC `2026-10-20T08:20:00Z`, fractions de seconde admises |
| `to` | Fin de période **exclue** (`window_start < to`) ; doit suivre `from` | idem |
| `intersection_id` | Zone : un carrefour | `INT_01` (`^INT_[0-9]{2,}$`) |
| `road_segment_id` | Zone : un tronçon | `ROAD_001` (`^ROAD_[0-9]{3,}$`) |
| `window_size_s` | Taille de fenêtre, **60 par défaut** (l'état d'alerte vient des fenêtres d'une minute) | 60 ou 300 |
| `congestion_state` | État stabilisé | `UNKNOWN`, `FREE_FLOW`, `SLOW`, `CONGESTED` |
| `run_id` | Une exécution | 1 à 80 caractères |
| `source_type` | Une provenance | `SIMULATED`, `REAL_HISTORICAL`, `REAL_LIVE` |

Les filtres se combinent (et logique). Une période vide ou une zone sans donnée donne une page vide, pas une erreur.

## 3. Pagination

- `limit` : 1 à 500, **100 par défaut**. `cursor` : curseur opaque lu dans `next_cursor` de la page précédente (512 caractères au plus) ; `next_cursor` vaut `null` sur la dernière page.
- **Tri fixe** : `window_start` décroissant, puis tronçon, puis exécution, en ordre d'octets (`COLLATE "C"`), donc identique quelle que soit la langue de la base.
- **Curseur par position, pas par décalage** : il retient la dernière ligne vue ; une ligne chargée entre deux pages ne décale pas la suite, et deux pages ne se chevauchent jamais, même quand plusieurs fenêtres ont le même début.
- Un curseur qu'on n'a pas obtenu de ce service donne 422 (`query.cursor`). Il vaut pour les mêmes filtres que la page qui l'a émis ; changer de filtre en cours de route donne un résultat valide mais sans signification.

## 4. Identifiant d'un indicateur

`<run_id>:<tronçon>:<taille de fenêtre>:<début en millisecondes depuis 1970>`, par exemple `run-demo-0001:ROAD_001:60:1792484400000` : c'est l'`id` de l'événement `novaria.traffic.indicator.v1`.
Il se lit **de droite à gauche** (un `run_id` peut contenir des deux-points) et se retrouve par la clé primaire de la table, donc sans balayage. Un identifiant mal formé ou inconnu donne **404**, comme le contrat le décrit (il ne prévoit pas de 422 pour cette route).
La vue SQL et le code Python fabriquent le même identifiant (un test le compare sur chaque ligne).

## 5. Provenance : la table `dwh.dim_run`

Le contrat exige, pour un indicateur simulé, `provenance.scenario_id` et `provenance.seed` ; pour un jeu historique, `dataset_id`. Les faits ne gardent que `run_id` et `source_type` :
le reste est dans **`dwh.dim_run`** (une ligne par exécution), avec les mêmes règles que le contrat, imposées par la base. Choix du 30/10/2026, voir le journal d'usage de l'IA.

- **Une exécution non enregistrée dans `dim_run` n'apparaît pas dans l'API**, ni une exécution dont le `source_type` diffère de celui de ses faits. C'est voulu (pas d'indicateur sans provenance complète) mais **silencieux** : si une donnée chargée manque à l'écran, c'est le premier endroit à regarder.
- **Qui enregistre les exécutions ?** Celui qui produit les faits : le simulateur (MS-07) et le chargeur ETL. **Aucun des deux ne le fait encore** : le chargeur de DAT-06 écrit des faits sans enregistrer leur exécution. Point ouvert, à reprendre avec eux.
- Enregistrer à la main une exécution (administrateur ou `svc_traitement`) :

```sql
INSERT INTO dwh.dim_run (run_id, source_type, scenario_id, seed)
VALUES ('preuve-dat06', 'SIMULATED', 'demo', 0);                       -- simulée : scénario et graine obligatoires
INSERT INTO dwh.dim_run (run_id, source_type, dataset_id)
VALUES ('paris-2026-10-17', 'REAL_HISTORICAL', 'paris-comptages-routiers');  -- historique : jeu obligatoire
```

## 6. Erreurs

Format `application/problem+json` avec `correlation_id`.

| Cas | Code HTTP | `code` |
|---|---|---|
| Pas de jeton valide | 401 | `UNAUTHENTICATED` |
| Paramètre hors contrat (borne, motif, valeur admise, date impossible, `to` avant `from`, curseur inconnu) | 422 | `VALIDATION_ERROR`, avec `errors[].field` (`query.limit`…) et un message en français sans la valeur saisie |
| Indicateur inconnu ou identifiant mal formé | 404 | `NOT_FOUND` |
| Entrepôt non configuré ou injoignable | 503 | `UPSTREAM_UNAVAILABLE` (sans adresse ni mot de passe) |

Le format 422 Problem vaut désormais pour **toutes** les routes du service (BE-06 reste à faire pour 404, 405 et 500 hors de ces routes).

## 7. Preuves

| Preuve | Contenu |
|---|---|
| `tests/contract/test_indicators_contract.py` | Les paramètres de chaque route sont ceux du contrat (noms, bornes, motifs, valeurs admises) ; chaque réponse (page, détail, derniers indicateurs, erreurs) est validée contre les schémas `Indicator`, `IndicatorPage` et `Problem` ; filtres de période et de zone, pagination, 401, 404, 422 ; valeurs nulles présentes comme `null` ; provenance sans champ vide |
| `tests/unit/` | Identifiant et curseur, forme du SQL (colonnes, filtres liés, ordre, reprise du curseur), lecture seule |
| `tests/integration/test_indicators_postgres.py` | Sur un vrai PostgreSQL migré par les migrations du dépôt : contraintes de `dim_run`, vue, **accord du dépôt SQL et du dépôt en mémoire** sur 15 jeux de filtres et 3 tailles de page, ordre d'octets des `run_id`, écriture refusée sur la connexion de lecture, réponses de l'API sur de vraies lignes (avec une session de base en fuseau de Tokyo) validées contre le contrat |

Résultats du 31/10/2026 (poste Windows) : 443 tests passent sans base (comme dans la CI) et 65 autres contre PostgreSQL 16 sous Docker, soit 508 ; couverture 99 %.
Essai de bout en bout : fenêtres de démonstration chargées par `dev.py etl-charger`, exécution enregistrée dans `dim_run`, serveur `uvicorn` : sans jeton 401 ; avec un jeton, page de 3 indicateurs puis page suivante, détail 200, identifiant inconnu 404, filtre carrefour et période (24 fenêtres de 5 minutes), `limit=0` refusé avec `query.limit`.
Preuve sous Linux : [À COMPLÉTER par Manoa Robel].

## 8. Limites et points ouverts

| Sujet | Position actuelle |
|---|---|
| Enregistrement des exécutions (`dim_run`) | À faire par le simulateur et le chargeur ETL ; sans lui, l'API reste vide |
| Prévisions (`/forecasts`), tronçons (`/road-segments`), carrefours (`/intersections`) | Hors de BE-04 ; même contrat, routes non implémentées |
| Compte de lecture | L'API lit avec `svc_traitement` (déjà donné au service), en session lecture seule, plutôt qu'avec `svc_lecture` : un test de la pile interdit ce second compte dans les services |
| Fenêtre de 5 minutes | Servie à la demande (`window_size_s=300`) ; l'état de ces fenêtres est un point ouvert du dictionnaire (section 12). **Piège constaté** : les fenêtres de démonstration du chargeur (DAT-06) sont de 5 minutes ; sans `window_size_s=300`, la liste (60 par défaut) et `latest` (une minute seulement, par contrat) sont vides |
| Index | La clé primaire de la table sert le détail ; les listes parcourent l'index `window_start`. À mesurer sur un gros run avant d'ajouter d'autres index |
| Cache | Aucun ; la lecture est directe |
