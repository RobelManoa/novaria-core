# Journalisation d'audit et statistiques d'usage (BE-05)

Issue BE-05 (#65). Exigence EXG-API-03, règle de gestion RG-22. Chaque appel authentifié laisse une entrée dans la collection MongoDB `audit_logs` (qui, quoi, quand, résultat), et chaque appel est compté dans `usage_stats` (par point d'accès et par heure). Le journal ne contient ni secret ni donnée personnelle. Preuve : [capture MongoDB](../03-donnees/preuve-be05-audit-mongodb.md).

Abréviations : **JWT** (JSON Web Token, jeton d'accès signé), **UUID** (identifiant unique universel, ici l'identifiant d'un compte), **UTC** (temps universel coordonné), **ASGI** (interface entre un serveur web Python et l'application).

## 1. Ce qui est audité

| Appel | Entrée dans `audit_logs` | Compté dans `usage_stats` |
|---|---|---|
| Jeton valide, accepté (200, 201…) | Oui, `outcome` = `ok` | Oui |
| Jeton valide, rôle insuffisant (403) | Oui, `outcome` = `denied` | Oui |
| Jeton valide, requête refusée ou en erreur (404, 409, 422, 500…) | Oui, `outcome` = `error` | Oui |
| Tentative de connexion `POST /api/v1/auth/login`, réussie | Oui, `actor` = compte connecté | Oui |
| Tentative de connexion refusée (401) ou mal formée (422) | Oui, `actor` = `anonymous` | Oui |
| Sans jeton, jeton illisible, expiré, signé avec un autre secret, compte supprimé ou désactivé | **Non** | Oui |
| Chemin inconnu | **Non** | Oui, sous la clé fixe `UNMATCHED` |
| Sonde de santé `GET /api/v1/health` | **Non** | **Non** |

Pourquoi un appel sans jeton valide n'entre pas dans `audit_logs` : le journal répond à « qui a fait quoi ». Sans jeton valide, personne n'est identifié, et n'importe qui sur le réseau pourrait remplir la collection (qui est illimitée en local). Ces appels restent visibles par le compteur et par le journal applicatif (`app.access`). Les tentatives de connexion sont l'exception voulue : une série de connexions refusées est un signal de sécurité qui doit rester traçable.

La sonde de santé est appelée par Docker toutes les 15 secondes : l'auditer produirait 5 760 entrées par jour sans information.

Le résultat suit le code HTTP : sous 400, `ok` ; 401, 403 et 429 (limite de débit de la connexion, BE-08), `denied` ; toute autre erreur, `error` (valeurs imposées par le validateur de la collection).

## 2. Ce qui est écrit (liste fermée)

Une entrée `audit_logs` contient exactement ces champs, et le code ne sait pas en écrire d'autres (`build_audit_entry`, `app/services/audit.py`) :

| Champ | Contenu | Exemple |
|---|---|---|
| `ts` | Début de l'appel, en UTC | `2026-11-03T14:26:31.941Z` |
| `service` | Nom du service | `traitement` |
| `actor` | Identifiant (UUID) du compte, ou `anonymous` | `67e2d36d-5358-49e3-a3bc-1088827ac591` |
| `action` | Méthode et **modèle** de la route | `GET /api/v1/users/{user_id}` |
| `outcome` | `ok`, `denied` ou `error` | `ok` |
| `correlation_id` | Identifiant de corrélation de l'appel (le même que l'en-tête `X-Correlation-ID` de la réponse et que les journaux applicatifs) | `d5891389-ccce-4da7-8780-7a85bcd54ead` |
| `details.status` | Code HTTP | `200` |
| `details.duration_ms` | Durée en millisecondes, une décimale | `34.5` |
| `details.role` | Rôle du compte au moment de l'appel (absent pour une connexion) | `admin` |
| `details.path_params` | Paramètres de chemin **qui sont des UUID**, sinon absent | `{ user_id: '…' }` |

**Jamais écrit** : le corps de la requête (donc ni mot de passe ni nom d'utilisateur saisi), les en-têtes (donc ni le jeton ni le navigateur), la chaîne de requête, l'adresse IP, le nom d'utilisateur, le message d'une exception.

Comment c'est garanti, et non seulement convenu :

1. **Le middleware ne voit rien de sensible.** Il lit seulement la méthode, le chemin, le code de réponse, l'heure, l'identifiant de corrélation et ce que la dépendance d'authentification a posé sur la requête (identifiant et rôle du compte). Il ne lit ni le corps, ni les en-têtes, ni la chaîne de requête.
2. **L'entrée est construite à partir d'une liste fermée de champs**, pas copiée depuis la requête. Un champ ajouté plus tard à la requête n'arrive pas dans le journal.
3. **Les paramètres de chemin sont filtrés**. Seuls les UUID passent. Une valeur inconnue pourrait être un jeton collé dans l'adresse par erreur.
4. **Le nom de la route est son modèle** (`/users/{user_id}`), tiré des routes publiées par l'application. Un chemin que l'appelant invente ne devient jamais une clé : il est compté sous `UNMATCHED`.
5. **L'acteur est un identifiant**, pas un nom d'utilisateur. Le nom reste dans le schéma `app`, où il est protégé par ses propres règles.
6. **Les tests le vérifient** : après un scénario qui utilise un jeton, des mots de passe, des noms d'utilisateur, une adresse IP, un navigateur et un jeton collé dans l'adresse, le texte de tout le journal et des compteurs est cherché pour chacune de ces valeurs (`test_nothing_secret_or_personal_reaches_the_journal`). La même recherche est faite sur la vraie collection (test d'intégration) et sur la capture MongoDB.

Le champ `actor` est un identifiant de compte (donnée pseudonymisée) : c'est ce qui permet de répondre à « qui » ; sans lui, le journal n'aurait pas de sens. Le registre des données personnelles (RG-23) reste vrai : aucune donnée d'usager final n'est stockée.

## 3. Compteurs d'usage

`usage_stats` garde **une ligne par point d'accès et par heure UTC** : `endpoint` (`GET /api/v1/users`), `bucket_start` (début de l'heure), `count`. L'écriture est un `update_one` avec `$inc` et `upsert` : atomique, sans lecture préalable. Si deux premiers appels de l'heure créent la ligne en même temps, l'index unique `uniq_endpoint_bucket` en refuse un, qui recommence sur la ligne existante (test : 50 appels simultanés, un seul document, `count` = 50).

Durée de la tranche : **1 heure**. Raisons : le volume attendu en local est faible (quelques centaines d'appels par jour) ; une heure donne 24 lignes par point d'accès et par jour, lisibles à la main ; une tranche d'une minute multiplierait les lignes par 60 sans gain pour la soutenance. Cela règle le point ouvert « Durée de la tranche de `usage_stats` » du dictionnaire de données (section 12). Changer la durée plus tard ne casse rien : les anciennes lignes gardent leur début de tranche.

La clé est le **modèle** de la route : `GET /api/v1/users/{user_id}` regroupe tous les comptes, les compteurs ne croissent donc pas avec le nombre d'utilisateurs.

## 4. Panne de MongoDB

L'écriture est **au mieux** : elle se fait après l'envoi de la réponse, dans un fil séparé, et une erreur ne change jamais la réponse du client. Preuve réelle : MongoDB arrêté, trois appels authentifiés répondent 200 en 14 à 19 ms ([capture](../03-donnees/preuve-be05-audit-mongodb.md)).

| Mécanisme | Valeur | Pourquoi |
|---|---|---|
| Attente maximale d'un serveur | 2 s | Une base éteinte ne bloque pas un fil plus longtemps |
| Pause après un échec | 10 s | Pendant la pause, les événements sont écartés sans essayer : une base éteinte ne ralentit pas chaque appel |
| Compteur `dropped` | Un par événement perdu | Savoir combien ont été perdus |
| Journal applicatif | Une ligne d'erreur par perte : type d'erreur, point d'accès, total perdu | Alerter sans écrire l'adresse de la base ni son message d'erreur (qui peut contenir l'identifiant de connexion) |

**Limite assumée** : un appel dont l'écriture échoue **n'a pas d'entrée d'audit**. Garantir une entrée à chaque appel exigerait de refuser l'appel quand MongoDB est indisponible, ce qui rendrait l'API dépendante d'une base de journalisation. Le choix inverse a été retenu pour une API de consultation ; il est à reconsidérer pour les commandes de feux (EXG-REP-04), qui relèvent d'un autre service. Pendant la panne, quelques appels déjà en cours (jusqu'à 2 s) peuvent tenter l'écriture avant que la pause ne démarre : ils sont tous comptés dans `dropped`.

Une connexion HTTP réutilisée par un navigateur peut attendre la fin de l'écriture de l'appel précédent avant d'être servie : au pire 2 s, une fois, au début d'une panne.

## 5. Où c'est dans le code

| Fichier | Rôle |
|---|---|
| `app/core/audit.py` | Middleware ASGI : mesure l'appel, retrouve le modèle de route, appelle l'observateur après la réponse |
| `app/services/audit.py` | Règles : qui est audité, contenu de l'entrée, résultat, tranche, pause après échec. Aucune dépendance à MongoDB |
| `app/repositories/audit.py` | Écriture dans MongoDB (`insert_one`, `update_one` avec `$inc`) |
| `app/db/observer.py` | Construit l'observateur à partir de `AUDIT_MONGO_URL` |
| `app/api/deps.py`, `app/api/v1/auth.py` | Posent l'identifiant et le rôle du compte sur la requête (jeton accepté ; connexion réussie) |

L'architecture suit [ADR-010](../01-architecture/adr/ADR-010-architecture-hexagonale.md) : les règles ne connaissent pas MongoDB, qui est branché derrière deux interfaces. Le middleware est placé **à l'intérieur** de celui qui pose l'identifiant de corrélation, pour le retrouver.

Sans `AUDIT_MONGO_URL`, rien n'est écrit et un avertissement est journalisé une fois : les tests et le poste sans MongoDB continuent de fonctionner.

## 6. Compte MongoDB et exception à la règle « un compte par service »

`audit_logs` et `usage_stats` ne s'écrivent qu'avec le compte `svc_backend` (rôle `role_backend` : lire et insérer dans `audit_logs`, lire, insérer et modifier dans `usage_stats`). Le compte du service de traitement (`svc_traitement`) n'a aucun droit sur ces collections. Comme pour `svc_app` (BE-03), le service qui porte l'API métier reçoit donc **une seconde adresse**, `AUDIT_MONGO_URL`, qui contient `svc_backend` ; `MONGO_URL` (compte `svc_traitement`) est inchangée. Aucun autre service ne reçoit `AUDIT_MONGO_URL` ni `svc_backend` : le test de la pile (`scripts/dev/test_compose.py`) le vérifie.

Le compte ne peut ni modifier ni supprimer une entrée d'audit (droits `find` et `insert` seulement) : **le journal ne se réécrit pas**. Test sur la vraie base : `update`, `delete` et `drop` sont refusés (erreur 13, non autorisé).

Cette exception disparaît si l'API métier redevient un service à part (point ouvert n° 1 des diagrammes C4).

## 7. Limites et points ouverts

| Sujet | Position actuelle | Suite |
|---|---|---|
| Entrée perdue si MongoDB est indisponible | Assumé (section 4) | À reconsidérer pour les commandes de feux |
| Conservation | Illimitée en local, comme le dictionnaire de données (section 10) ; aucun index à durée de vie sur `audit_logs` | Décider d'une durée avec le contrôle des durées de conservation, avant un déploiement |
| Appels sans jeton valide | Comptés, non journalisés (section 1) | À reconsidérer si un besoin de détection d'intrusion apparaît (alerte sur les 401 répétés) |
| Journal applicatif (`app.access`) | Il écrit le chemin reçu : un jeton collé dans l'adresse y apparaîtrait. Non traité par BE-05, qui ne porte que sur MongoDB ; l'audit, lui, l'écarte | BE-06 (format d'erreur et journaux) |
| Lecture du journal | Aucune route ne lit `audit_logs` ; la lecture se fait dans MongoDB | À ajouter si le tableau de bord doit l'afficher (rôle `admin`) |
| Commandes de feux | Auditées par le service de réponse extérieure (`svc_reponse` a le droit d'insérer dans `audit_logs`) ; non traité ici | MS-12 |
| Durée de l'appel | Mesurée dans le middleware, donc sans l'attente de l'écriture dans MongoDB, mais avec l'authentification | |
