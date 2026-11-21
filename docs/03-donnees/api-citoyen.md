# API citoyen : l'état et les alertes publiques, derrière la passerelle

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsable : Manoa Robel (issue CIT-03), relecture croisée par Daddy Luciano
Dernière mise à jour : 20/11/2026
Issue de suivi : CIT-03 (#271), dépend de CIT-02 (#270) · Décision : [ADR-030](../01-architecture/adr/ADR-030-application-citoyenne-perimetre-et-acces.md) · Contrats : `contracts/openapi/traitement.openapi.yaml` et `alerte.openapi.yaml`
Statut : à valider par les deux membres (relecture de la pull request)

Critère d'acceptation : **la passerelle sert l'état et les alertes publiques ; une écriture ou une route interne est refusée.** Preuve : les tests de l'API (section 6) et la [capture de `curl`](sorties-api-citoyen/curl-2026-11-20.txt) via la passerelle (section 7).

> **Données simulées.** Tout ce que ces routes servent vient du simulateur du dépôt : le champ `simulated` le dit dans chaque élément, et l'application citoyenne devra l'afficher (ADR-027). Aucune donnée réelle ni personnelle.

Abréviations : **API** (Application Programming Interface, interface de programmation), **DTO** (Data Transfer Object, objet qui décrit exactement ce qui sort d'une API), **SQL** (Structured Query Language), **UTC** (Coordinated Universal Time, temps universel coordonné), **CORS** (Cross-Origin Resource Sharing, partage entre origines).

## 1. En bref

| Tâche de l'issue | Réalisé | Où |
|---|---|---|
| Implémenter les routes dans le service d'alerte usager ou un service dédié, selon l'ADR | Pas de nouveau service (ADR-030, option F) : l'**état** dans `traitement`, les **alertes** dans `alerte` | `services/traitement/app/api/v1/public.py`, `services/alerte/app/api/v1/public.py` |
| Lire l'état de congestion à partir des indicateurs existants, sans nouvelle source | Une requête sur `dwh.v_indicator` et le référentiel `dwh.dim_road_segment`, **par le compte en lecture seule** déjà utilisé par l'API des indicateurs | `SqlIndicatorRepository.latest_public` |
| Aucun identifiant de capteur ni donnée personnelle dans les réponses | Six champs par route, **liste blanche** à quatre niveaux (section 3) ; aucun nom d'opérateur, aucun capteur | Section 3 |
| `/metrics` et journaux sans valeur de requête | Déjà vrai pour les deux services ; **prouvé** pour les routes publiques avec une chaîne de requête piégée | Section 4 |

## 2. Les deux routes

| | `GET /api/v1/public/congestion` | `GET /api/v1/public/alerts` |
|---|---|---|
| Service | `traitement` | `alerte` |
| Source | `dwh.v_indicator` (dernière fenêtre d'une minute de chaque tronçon, **run le plus récent**) joint à `dwh.dim_road_segment` (côté du tronçon) | `alertes.alert`, type `CONGESTION`, état différent de `RESOLVED` |
| Ordre | `road_segment_id` | `opened_at` décroissant, puis `alert_id` |
| Taille | un élément par tronçon du run | **100 au plus** |
| Champs | `road_segment_id`, `intersection_id`, `approach`, `state`, `updated_at`, `simulated` | `alert_id`, `road_segment_id`, `intersection_id`, `severity`, `opened_at`, `simulated` |
| Vide | `{"items": []}` (entrepôt sans indicateur) | `{"items": []}` (aucune alerte en cours) |

`updated_at` est la **fin** de la dernière fenêtre d'une minute (son début plus 60 s), en UTC avec `Z`. `simulated` vaut vrai quand `provenance.source_type` est `SIMULATED`. Aucun paramètre en v1 : rien à injecter, rien à filtrer.

## 3. Ce qui ne sort jamais, et comment c'est garanti

Liste de l'ADR-030 (section 4.4) : données brutes, capteurs, feux, nom de l'opérateur, cause, règle, épisode, historique, provenance interne, défauts de capteur. Quatre garde-fous empilés :

| Niveau | Garde-fou | Ce qui se passe si on l'oublie |
|---|---|---|
| 1. Base | La requête de l'état ne sélectionne que **six colonnes** (pas la ligne d'indicateur entière) ; celle des alertes lit une ligne mais la route ne copie que six champs | Une colonne ajoutée à la vue n'arrive jamais jusqu'à la route |
| 2. Mappeur | Écrit **champ par champ** (`PublicSegmentState.from_row`, `public_alert_out`) | Un champ ajouté au modèle interne ne sort pas |
| 3. Schéma de réponse | `extra="forbid"` : un champ de plus est une erreur, pas une fuite | Le test `test_the_mapper_copies_six_fields_and_nothing_else` échoue |
| 4. Contrat | `additionalProperties: false`, six champs obligatoires, liste bornée ; la liste est comparée à celle de l'ADR par `scripts/dev/test_contrat_public.py` | Le contrat et la décision ne peuvent pas diverger |

Seul le type `CONGESTION` est public : un `SENSOR_FAULT` (capteur muet) ou un `TRAFFIC_ANOMALY` regardent l'exploitation. Une alerte **acquittée** reste « en cours » et son `acknowledged_by` (nom d'un opérateur : donnée personnelle) n'apparaît pas : un test acquitte une alerte avec un nom reconnaissable et vérifie qu'il n'est nulle part dans la réponse.

## 4. Anonymat, journaux, audit, métriques

| Sujet | Ce qui est vrai | Preuve |
|---|---|---|
| Aucune identité lue | Les deux routes n'ont **aucune dépendance d'authentification** ; la passerelle retire en plus le jeton, le cookie et l'identité (`gateway/citoyen.conf`) | Tests : un jeton valide ou faux ne change pas la réponse |
| Journal des services | La ligne d'accès contient la méthode, le **chemin** et le code, **jamais la chaîne de requête** | Test : `?jeton=valeur-secrete&nom=Dupont` n'apparaît dans aucune ligne `app.*` des deux services |
| `/metrics` | L'étiquette `route` est le **modèle de route** ; aucune valeur de requête | Même test, sur la sortie de `/metrics` |
| Audit (`traitement`) | Un appel **sans identité** n'écrit **aucune entrée** d'audit ; il est seulement **compté** sous `GET /api/v1/public/congestion` | Test sur le vrai observateur : 0 entrée d'audit, 1 compteur |
| Journal de la passerelle | Pour l'espace public, l'adresse est **remplacée par `-`** et n'est pas transmise aux services (`X-Forwarded-For` vide) ; la limite de débit la garde en mémoire seulement. Le journal d'**erreurs** nomme encore l'adresse quand un service est injoignable | Fait par CIT-06 ([sécurité de l'accès public](../04-devsecops/securite-acces-public.md)), limite restante assumée |

## 5. Passerelle (acquis de CIT-02)

Débit limité à 2 requêtes par seconde par adresse (rafale de 10), `Cache-Control: public, max-age=5` sur un 200 et `no-store` sinon, écriture refusée (405, `Allow: GET, OPTIONS`), tout autre chemin de `/api/v1/public/` en 404. Les routes ne sont lues qu'au démarrage de la passerelle : après un changement des contrats, `docker compose exec -T passerelle nginx -s reload`.

## 6. Preuve : tests

| Suite | Résultat |
|---|---|
| `services/alerte`, `tests/unit/test_public_api.py` | 21 tests : sans jeton, six champs, ni opérateur ni cause ni provenance, défaut de capteur absent, alerte résolue absente, alerte acquittée présente, plus récentes d'abord, borne de 100, écritures refusées, chemins inconnus, base arrêtée (503 sans détail), requête non journalisée |
| `services/traitement`, `tests/unit/test_public_api.py` | 20 tests : mêmes principes pour l'état, dernier run et dernière fenêtre seulement, côté du tronçon, `updated_at` en UTC, `simulated`, aucun jeton utile, écritures refusées, audit sans identité |
| `services/traitement`, `tests/integration/test_indicators_postgres.py` (vrai PostgreSQL, base jetable) | 2 tests de plus (37 passent) : la requête publique donne les mêmes tronçons, états et fenêtres que les indicateurs existants, avec les bons côtés ; la route sur de vraies lignes, session en fuseau de Tokyo, rend de l'UTC |
| Suites existantes adaptées | Les contrats d'authentification, d'audit et d'erreurs de `traitement`, et le test de couverture du contrat d'`alerte`, tiennent compte d'une route sans jeton ; **aucun test supprimé** |
| `scripts/dev/test_contrat_public.py` et `gateway/tests/` | Contrat, liste blanche de l'ADR, passerelle réelle (CIT-02) |
| `dev.py acces` | Famille « api public » : accès 8/8, refus 52/52, **accès interdits accordés : 0** ([sortie](../05-cloud-aws/sorties-acces/acces-citoyen-servi-2026-11-20.txt)) ; famille « api public (abus) » (CIT-06) : témoins 3/3, abus refusés 19/19 ([sortie](../05-cloud-aws/sorties-acces/acces-citoyen-securite-2026-11-21.txt)) |

## 7. Preuve : capture de `curl` via la passerelle

[`sorties-api-citoyen/curl-2026-11-20.txt`](sorties-api-citoyen/curl-2026-11-20.txt) : pile locale, après `dev.py flux-complet N1 N2 N3 N4` (un run de quatre capteurs). Extrait :

| Appel | Réponse |
|---|---|
| `GET /api/v1/public/congestion` | **200**, `Cache-Control: public, max-age=5`, quatre tronçons de `INT_01` avec leur côté (N, E, S, W), leur état, `updated_at`, `simulated: true` |
| `GET /api/v1/public/alerts` | **200**, des alertes de congestion en cours, six champs chacune |
| idem avec `Authorization` et `Cookie` | même réponse : ils sont ignorés |
| `POST` et `DELETE` sur une route publique | **405**, `Allow: GET, OPTIONS`, `Cache-Control: no-store` |
| `GET /api/v1/public/signals`, `/public/indicators` | **404** (route inconnue) |
| `GET /api/v1/measurements` (dépôt interne) | **404** |
| `GET /api/v1/indicators/latest` sans jeton | refusé : la route de l'équipe reste protégée |

## 8. Limites et points ouverts pour la relecture croisée

| N° | Point | État |
|---|---|---|
| 1 | L'état est celui du **run le plus récent** de l'entrepôt : si deux runs se chevauchent (le simulateur et un essai), seul le dernier écrit est montré (vu le 20/11/2026 : après un essai d'une seule mesure, un seul tronçon apparaissait en `UNKNOWN`). Le jeu de démonstration d'un seul run ne le montre pas | Limite ; à reconsidérer si plusieurs runs coexistent |
| 2 | Les alertes « en cours » sont **toutes les alertes de congestion non résolues** de la pile : des alertes de runs anciens y restent tant qu'elles ne sont pas résolues (40 sur la pile de travail le 20/11/2026) | Donnée de la pile de travail, pas un défaut de la route ; une règle d'ancienneté serait une décision |
| 3 | La passerelle répond le 405 avec `Content-Type: application/octet-stream` au lieu de `application/problem+json` (corps JSON correct) | Défaut du générateur de routes, **existant pour toutes les routes**, non corrigé ici |
| 4 | CORS pour l'origine de l'application citoyenne | Fait par CIT-06 : `CORS_PUBLIC_ORIGINS`, liste dédiée, lecture seule |
| 5 | Adresse du client dans le journal de la passerelle | Fait par CIT-06 pour l'espace public (voir section 4) |
| 6 | Les tests d'intégration contre PostgreSQL exigent `NOVARIA_TEST_POSTGRES_ADMIN_URL` : ignorés sans elle, donc **pas rejoués par la CI** si elle ne la définit pas | À vérifier |
| 7 | Vérifié sous Linux ; non vérifié sous Windows | À rejouer par le binôme |

## 9. Rejouer

| Besoin | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Voir l'état public | `curl -s http://127.0.0.1:8000/api/v1/public/congestion` | `(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/public/congestion).Content` |
| Voir les alertes publiques | `curl -s http://127.0.0.1:8000/api/v1/public/alerts` | `(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/public/alerts).Content` |
| Faire un run à montrer (4 capteurs, 8 minutes) | `python3 scripts/dev/dev.py flux-complet N1 N2 N3 N4` | `py -3 scripts/dev/dev.py flux-complet N1 N2 N3 N4` |
| Matrice d'accès, famille « api public » | `python3 scripts/dev/dev.py acces` | `py -3 scripts/dev/dev.py acces` |
| Tests du service d'alerte | `cd services/alerte && python3 -m pytest tests/unit/test_public_api.py` | `cd services\alerte; py -3 -m pytest tests\unit\test_public_api.py` |
| Tests du service de traitement | `cd services/traitement && python3 -m pytest tests/unit/test_public_api.py` | `cd services\traitement; py -3 -m pytest tests\unit\test_public_api.py` |
| Passerelle déjà lancée : relire les routes | `docker compose exec -T passerelle nginx -s reload` | idem |
