# Matrice d'accès : rôles × ressources, essais d'autorisation et de refus (CLD-18)

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano (responsable de l'issue) et Manoa Robel (relecture croisée)
Dernière mise à jour : 17/11/2026
Issue de suivi : CLD-18 (#91), dépend de CLD-09 (#52, fermé)
Statut : à valider par les deux membres (relecture de la pull request)

Critère d'acceptation : **les accès interdits sont refusés.** Preuve : ce document, section 6 : sur 363 essais réels (toutes les routes de l'API avec chaque rôle, tous les privilèges de chaque compte de base, un essai autorisé et un essai refusé par rôle, compte et utilisateur), **0 accès interdit accordé**. Les écarts que la matrice laisse ouverts (Kafka, dépôt des mesures) et trois droits manquants sur la pile de travail sont listés section 7.

Abréviations : **IAM** (Identity and Access Management, gestion des identités et des accès d'AWS), **JWT** (JSON Web Token, jeton signé), **API** (Application Programming Interface), **SSE** (Server-Sent Events), **ACL** (Access Control List, liste de contrôle d'accès), **TTL** (Time To Live, durée de vie d'un document), **ECS** (Elastic Container Service).

## 1. En bref

| Tâche de l'issue | Réalisé | Où | Preuve |
|---|---|---|---|
| Matrice rôles × ressources | `ops/matrice-acces.json`, versionnée : rôles de l'API, comptes PostgreSQL, utilisateurs MongoDB, producteurs et consommateurs Kafka. Tableaux de la section 3 | `ops/matrice-acces.json` | Section 3 |
| Un essai autorisé et un essai refusé par rôle | `dev.py acces` : sur les vrais composants, **chaque rôle, compte et utilisateur** a un essai autorisé et un essai refusé nommés (section 6.2), en plus des essais exhaustifs | `scripts/dev/acces.py` | Section 6 |

**Ce que ce document ne fait pas** : il ne crée aucun rôle, aucune politique ni aucune ressource AWS (ADR-023, ADR-025). L'équivalent local d'IAM est décrit section 2.

## 2. IAM et son équivalent local

| Dans AWS | Ici | Où c'est appliqué |
|---|---|---|
| Rôle IAM d'une personne ou d'un client de l'API | Rôle `viewer`, `operator` ou `admin` dans le jeton JWT | La **passerelle** (nginx et njs), puis chaque service qui relit le jeton |
| Rôle IAM d'une tâche ECS (un service accède à ses seules ressources) | Un **compte de connexion par service** dans PostgreSQL et un utilisateur par service dans MongoDB | Les bases elles-mêmes |
| Politique IAM (action, ressource, condition) | Une ligne de la matrice : rôle, ressource, lecture ou action | `ops/matrice-acces.json`, comparée à la pile par `dev.py acces` |
| Refus explicite par défaut | **Tout ce qui n'est pas dans la matrice est refusé** : un chemin absent des contrats est un 404, une route absente de la matrice fait échouer le banc, un privilège non déclaré est un écart | Contrats OpenAPI, catalogues des bases |
| Moindre privilège | Aucun compte de service n'est administrateur ; aucun service MongoDB ne peut supprimer | Section 3, vérifié section 6 |
| Journal des accès (CloudTrail) | Journaux de la passerelle (réponse et identifiant de requête) et journal d'audit MongoDB (`audit_logs`) | Non étendu par CLD-18 |

## 3. La matrice

### 3.1 API : rôles × ressources

Les rôles sont **ordonnés** : `viewer` < `operator` < `admin`. Un rôle supérieur peut tout ce que peut un rôle inférieur. « Lire » = `GET` ; « agir » = `POST`, `PATCH`.

| Ressource | Chemins | anonyme | `viewer` | `operator` | `admin` |
|---|---|---|---|---|---|
| Routes publiques | `/api/v1/health`, `POST /api/v1/auth/login` | oui | oui | oui | oui |
| **Routes publiques de l'application citoyenne** (CIT-02, [ADR-030](../01-architecture/adr/ADR-030-application-citoyenne-perimetre-et-acces.md)) | `GET /api/v1/public/congestion`, `GET /api/v1/public/alerts` | lire | lire | lire | lire |
| Écriture sur ces routes, et tout autre chemin sous `/api/v1/public/` | `POST`, `PUT`, `PATCH`, `DELETE` ; `/api/v1/public/indicators`, `/signals`, `/users`… | refusé (405 ; 404) | refusé | refusé | refusé |
| Profil du compte connecté | `/api/v1/auth/me` | — | lire | lire | lire |
| Indicateurs, carrefours, tronçons, prévisions, rapports | `/api/v1/indicators`, `/intersections`, `/road-segments`, `/forecasts`, `/reports` | — | lire | lire | lire |
| Alertes et flux temps réel | `/api/v1/alerts`, `/events/stream` | — | lire | lire, **acquitter, résoudre** | lire, acquitter, résoudre |
| Règles d'alerte (seuils) | `/api/v1/alert-rules` | — | lire | lire | lire, **modifier** |
| Feux et leurs commandes | `/api/v1/signals` | — | lire | lire, **commander** | lire, commander |
| Comptes utilisateurs | `/api/v1/users` | — | — | — | **lire, créer, modifier** |
| Dépôt des mesures | `/api/v1/measurements` | refusé (404) | refusé (404) | refusé (404) | refusé (404) |

Deux portes : la passerelle contrôle le jeton **et** le rôle avant tout service ; chaque service (traitement, alerte, réponse) relit le jeton lui-même ([passerelle](../../gateway/README.md), section 3). La matrice est **comparée aux contrats OpenAPI** : le rôle exigé de chaque route (`gateway/routes.json`, généré) doit être celui de la matrice, sinon le banc échoue.

### 3.2 PostgreSQL : comptes × schémas

Un compte de connexion par service, sans droit d'administration (`CREATEDB`, `CREATEROLE`, `SUPERUSER`, `BYPASSRLS` absents). `S` = SELECT, `I` = INSERT, `U` = UPDATE, `D` = DELETE, sur **toutes** les tables et vues du schéma. `novaria_admin` (migrations, sauvegardes) est hors matrice : aucun service ne l'utilise.

| Compte | Usage | `app` | `dwh` | `alertes` | `ops` |
|---|---|---|---|---|---|
| `svc_app` | API métier (comptes) | S I U D, et créer | — | — | — |
| `svc_traitement` | Traitement : écrit l'entrepôt | — | S I U D | — | — |
| `svc_alerte` | Alerte usager | — | — | S I U D | — |
| `svc_lecture` | API de consultation, analyses | — | S | S | — |

### 3.3 MongoDB : utilisateurs × collections

`F` = find (lire), `I` = insert, `U` = update. **Aucun utilisateur ne peut supprimer** (le TTL de MongoDB expire les documents).

| Utilisateur | `raw_events` | `rejects` | `processing_stats` | `ingestion_runs` | `audit_logs` | `usage_stats` | `model_runs` |
|---|---|---|---|---|---|---|---|
| `svc_collecte` | F I | F I | — | — | — | — | — |
| `svc_traitement` | F | F I | F I U | F I U | — | — | — |
| `svc_reponse` | — | — | — | — | F I | — | — |
| `svc_backend` | — | — | — | — | F I | F I U | — |
| `svc_ml` | F | — | F | — | — | — | F I U |

### 3.4 Kafka : producteurs et consommateurs × sujets (**déclaré, non appliqué**)

Source : `contracts/topics.json`. **Le broker local n'a ni authentification ni autorisation** : cette matrice n'est pas appliquée (section 7, écart 1).

| Sujet | Producteur | Consommateur | Consommateur extérieur |
|---|---|---|---|
| `iot.raw` | collecte | traitement | — |
| `traffic.indicators` | traitement | alerte | tableau de bord |
| `traffic.recommendations` | traitement | réponse | — |
| `alerts.events` | alerte | alerte | tableau de bord |
| `signal.status` | réponse | alerte | tableau de bord |
| `errors.dlq` | collecte, traitement, alerte, réponse | — | revue manuelle |

## 4. Méthode des essais

`python3 scripts/dev/dev.py acces` compare la matrice à ce que la pile **fait**, sur les vrais composants :

| Famille | Essais | Ce qui est vérifié |
|---|---|---|
| API par la passerelle | **27 routes × 4 sujets** (anonyme, `viewer`, `operator`, `admin`), plus le dépôt des mesures avec chaque sujet | Anonyme : 401. Rôle trop faible : 403. Rôle suffisant : la requête atteint le service (n'importe quel code sauf 401 et 403) |
| API directe sur les services | Traitement, alerte, réponse, **sans la passerelle** : anonyme, `viewer` en lecture, `viewer` sur une route d'`operator` ou d'`admin` | Le service refuse aussi (défense en profondeur) |
| PostgreSQL, catalogue | 4 comptes × 4 schémas × 4 privilèges, plus l'administration et la création d'objets | Pour chaque case : **tous les objets du schéma ou aucun**, selon la matrice. Un droit partiel est un écart |
| PostgreSQL, essais réels | Par compte, une requête autorisée et une refusée, **connecté en tant que ce compte** | Refus = `permission denied` (une autre erreur ne compte pas comme un refus) |
| MongoDB, catalogue | 5 utilisateurs × 7 collections × 4 actions | Privilèges réels (hérités compris) égaux à la matrice ; une collection absente de la matrice est signalée |
| MongoDB, essais réels | Par utilisateur, une commande autorisée et une refusée | Refus = `Unauthorized` |

**Aucun essai ne modifie de donnée** : les chemins visent des identifiants inexistants, les corps sont vides, les écritures de base sont des `UPDATE … WHERE false` ou la suppression d'un identifiant absent. Trois comptes d'API jetables (un par rôle, mots de passe aléatoires) sont créés puis supprimés, même en cas d'erreur. Un essai raté (réseau, limitation de débit, panne d'un service) est rejoué une fois, puis **compté comme un échec**, jamais comme un succès.

Deux catégories d'échec, de gravité différente :

| Catégorie | Sens | Gravité |
|---|---|---|
| **Accès interdit accordé** | La matrice interdit, la pile a laissé passer | **Sécurité** : le critère de CLD-18 est « 0 » |
| Accès prévu refusé ou non concluant | La matrice autorise, la pile a refusé ou n'a pas répondu | Disponibilité, pas sécurité |

## 5. Lancer

| Besoin | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Rejouer tous les essais | `python3 scripts/dev/dev.py acces` ou `make acces` | `py -3 scripts/dev/dev.py acces` |
| Tests du banc, sans Docker (53 tests) | `python3 -m unittest discover -s scripts/dev -p "test_acces.py"` | `py -3 -m unittest discover -s scripts/dev -p "test_acces.py"` |

Prérequis : `.env` créé, pile démarrée (`dev.py up`), Docker. La commande ne modifie aucune donnée de la pile. Code de sortie 0 si tous les essais sont conformes, 1 sinon (les écarts connus de Kafka et de la collecte ne changent pas le code : ce sont des constats).

## 5 bis. Routes publiques de l'application citoyenne (CIT-02, 20/11/2026)

La matrice a deux clés de plus (`api.publiques_lecture`, `api.espace_public_interdit`) et le banc une famille d'essais, **`api public`** :

| Essai | Attendu | Sujets |
|---|---|---|
| `GET` sur chacune des deux routes | accès accordé, **sans jeton** ; un jeton d'équipe ne change rien | anonyme, `viewer`, `operator`, `admin` |
| `POST`, `PUT`, `PATCH`, `DELETE` sur chacune | **refusé par la passerelle** (405), y compris pour l'administrateur | les quatre sujets |
| `GET` sur cinq chemins de l'espace public hors liste (`indicators`, `signals`, `users`, `alert-rules`, `measurements`) | refusé (404) | les quatre sujets |

Le banc compare aussi la matrice aux contrats : une route publique de la matrice absente des contrats, ou une route de l'espace public des contrats absente de la matrice, est un échec (`verifier_la_matrice_contre_les_contrats`). Résultat du 20/11/2026 : `api public  accès accordés 8/8 · accès refusés 52/52`, **accès interdits accordés : 0** ([sortie complète](sorties-acces/acces-citoyen-2026-11-20.txt)). Limite : le banc prouve l'accès, pas le contenu des réponses. Le 20/11/2026, avant CIT-03, le service répondait 404 après avoir été atteint, ce que la matrice compte comme un accès accordé ; depuis CIT-03 les routes répondent 200 ([sortie](sorties-acces/acces-citoyen-servi-2026-11-20.txt), même résultat), et le contenu est prouvé par les tests de contrat et de l'API ([api-citoyen.md](../03-donnees/api-citoyen.md)).

## 6. Preuve : exécution du 17/11/2026

Poste Linux (Ubuntu), pile locale démarrée par `dev.py up` (13 conteneurs sains), sortie de `dev.py acces`, lignes raccourcies :

### 6.1 Résumé

```text
  api                      accès accordés 70/70 · accès refusés 42/42
  service direct           accès accordés 3/3 · accès refusés 6/6
  postgres (catalogue)     accès accordés 15/15 · accès refusés 69/69
  postgres (essai réel)    accès accordés 4/4 · accès refusés 4/4
  mongo (catalogue)        accès accordés 22/25 · accès refusés 115/115
  mongo (essai réel)       accès accordés 5/5 · accès refusés 5/5

360/363 essais conformes à la matrice, 2 écart(s) connu(s).
Accès interdits accordés : 0 (critère de CLD-18 : 0).  Accès prévus refusés ou non concluants : 3.
```

**Les 42 + 6 + 69 + 4 + 115 + 5 = 241 accès interdits ont tous été refusés.**

### 6.2 Un essai autorisé et un essai refusé par rôle

| Sujet | Essai autorisé | Essai refusé |
|---|---|---|
| anonyme | `POST /api/v1/auth/login` : HTTP 422 (route publique, corps vide refusé par la validation) | `GET /api/v1/indicators` : **HTTP 401** |
| `viewer` | `GET /api/v1/indicators` : HTTP 200 | `POST /api/v1/signals/…/commands` : **HTTP 403** (rôle exigé : `operator`) |
| `operator` | `POST /api/v1/alerts/…/acknowledge` : HTTP 404 (autorisation passée, identifiant inconnu : rien n'est modifié) | `PATCH /api/v1/alert-rules/…` : **HTTP 403** (rôle exigé : `admin`) |
| `admin` | `GET /api/v1/users` : HTTP 200 | `POST /api/v1/measurements` : **HTTP 404** (la passerelle ne l'expose à personne) |
| `svc_app` | `SELECT count(*) FROM app.users` : exécutée | `SELECT count(*) FROM dwh.fact_traffic_window` : **permission denied** |
| `svc_traitement` | `UPDATE dwh.fact_traffic_window … WHERE false` : exécutée | `SELECT count(*) FROM app.users` : **permission denied** |
| `svc_alerte` | `UPDATE alertes.alert … WHERE false` : exécutée | `SELECT count(*) FROM dwh.fact_traffic_window` : **permission denied** |
| `svc_lecture` | `SELECT count(*) FROM dwh.v_indicator` : exécutée | `UPDATE dwh.fact_traffic_window … WHERE false` : **permission denied** |
| `svc_collecte` (MongoDB) | `db.raw_events.countDocuments({})` : exécutée | `db.raw_events.deleteOne(…)` : **Unauthorized** |
| `svc_traitement` (MongoDB) | `db.processing_stats.countDocuments({})` : exécutée | `db.raw_events.insertOne(…)` : **Unauthorized** |
| `svc_reponse` | `db.audit_logs.countDocuments({})` : exécutée | `db.raw_events.countDocuments({})` : **Unauthorized** |
| `svc_backend` | `db.usage_stats.countDocuments({})` : exécutée | `db.raw_events.countDocuments({})` : **Unauthorized** |
| `svc_ml` | `db.model_runs.countDocuments({})` : exécutée | `db.raw_events.insertOne(…)` : **Unauthorized** |

### 6.3 Les écarts connus et les trois droits manquants

```text
Écarts connus (contrôle prévu et absent, non compté comme un succès) :
  [ÉCART] Kafka : 6 sujets, 14 droits de production ou de consommation déclarés dans contracts/topics.json, aucun appliqué
          `kafka-acls --list` : … SecurityDisabledException: No Authorizer is configured on the broker
  [ÉCART] Dépôt des mesures (POST /api/v1/measurements) : accessible sans jeton depuis le poste
          POST sans jeton : HTTP 422 (validation du corps atteinte : aucun contrôle d'accès devant)
[ÉCHEC] mongo (catalogue) · svc_traitement · ingestion_runs · find : attendu accès, droits réels : aucun
[ÉCHEC] mongo (catalogue) · svc_traitement · ingestion_runs · insert : attendu accès, droits réels : aucun
[ÉCHEC] mongo (catalogue) · svc_traitement · ingestion_runs · update : attendu accès, droits réels : aucun
```

## 7. Constats et écarts, pour la relecture croisée

| N° | Constat | Gravité | État |
|---|---|---|---|
| 1 | **Kafka n'a aucun contrôle d'accès.** Écouteurs `PLAINTEXT`, aucun autorisateur : n'importe quel client du poste peut produire ou consommer sur n'importe quel sujet. La matrice 3.4 est déclarée (ADR-009) mais **pas appliquée** ; le critère « les accès interdits sont refusés » n'est donc **pas atteint pour Kafka** | Écart de sécurité, limité au poste (port sur `127.0.0.1`) | **Non corrigé.** Il faudrait SASL et un autorisateur côté broker, puis des identifiants dans chaque service : un chantier à part, à décider |
| 2 | **Le dépôt des mesures n'a pas d'authentification** : un appel sans jeton atteint la validation. La passerelle ne l'expose pas (404) et le port n'est publié que sur `127.0.0.1` | Écart connu depuis MS-08 ([collecte](../03-donnees/collecte.md), section 3.1) | Non corrigé |
| 3 | Sur la pile de travail, `svc_traitement` n'a **aucun droit** sur `ingestion_runs` : la collection n'existe pas, la pile est plus ancienne que le script d'initialisation du dépôt (même retard que dans [restauration](../08-exploitation/restauration.md), limite 8). Le rôle manque à la pile, pas à la matrice. Direction **sûre** (trop restrictif), 3 cellules | Disponibilité | Non corrigé : l'initialisation ne rejoue que sur un volume vide |
| 4 | Un **503 transitoire** est apparu une fois sur `GET /api/v1/alert-rules` pour `viewer` : le service d'alerte a écrit « discarding closed connection » (un connecteur du pool PostgreSQL fermé) puis répondu 503 à la première requête. Non reproduit (6 essais). Le banc rejoue maintenant une fois un essai non concluant | Résilience du service d'alerte, **sans lien avec l'autorisation** | Constat, non corrigé |
| 5 | **La passerelle ne sait pas si un compte est actif** : un compte désactivé reste accepté par la passerelle jusqu'à l'expiration du jeton (30 minutes), mais refusé par `traitement` ; `alerte` et `reponse` ne relisent pas le compte ([passerelle](../../gateway/README.md), section 3) | Écart connu | Non corrigé |
| 6 | Le rôle `admin` peut tout ce que fait `operator` (héritage). Il n'existe pas de rôle qui administre les comptes **sans** commander les feux | Choix de conception | À valider |

## 8. Limites

| Limite | Conséquence |
|---|---|
| Vérifié sous **Linux seulement** ; les commandes PowerShell sont **non vérifiées** | À rejouer par le responsable de l'issue, Daddy Luciano |
| Une exécution consignée ; l'état de la pile est celui du moment (comptes, données) | Les essais sont répétables : `dev.py acces` |
| La matrice décrit l'**intention** ; `dev.py acces` prouve que la pile la suit **à cet instant**. Un nouveau service, une nouvelle route ou une nouvelle collection sans ligne dans la matrice fait échouer le banc (route inconnue) ou est signalé (collection) | Garde contre l'oubli, pas contre une dérive qui se produirait **entre** deux exécutions |
| Les essais d'API visent des identifiants inconnus : « autorisé » veut dire « l'autorisation est passée », pas « l'action a réussi » | Voulu : aucune donnée n'est modifiée |
| Le banc ne teste pas les droits du **compte administrateur** des bases (`novaria_admin`) ni du conteneur Docker | Hors matrice : l'accès au poste est l'accès à tout |
| Pas de test d'élévation (modifier son propre rôle dans le jeton) : la signature HS256 est vérifiée par la passerelle et les services ([sécurité applicative](../04-devsecops/securite-applicative.md), BE-03, MS-13) | Couvert par leurs propres tests, non rejoué ici |
