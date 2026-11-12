# Passerelle d'API

**MS-13 (issue #132).** Un nginx avec son module njs (`nginxinc/nginx-unprivileged`, variante complète : la variante « slim » n'a pas njs) qui reçoit tous les appels de l'API sur `127.0.0.1:${GATEWAY_PORT:-8000}`. Il **contrôle le jeton et le rôle avant tout service**, limite le débit, applique CORS, pose les en-têtes de sécurité, puis envoie la requête au service propriétaire. Décision : [ADR-029](../docs/01-architecture/adr/ADR-029-passerelle-et-authentification.md).

**Critère : un appel sans jeton valide est refusé pour tous les services.** Preuve : [`tests/test_gateway.py`](tests/test_gateway.py), qui essaie **chaque route des contrats OpenAPI** sur la vraie passerelle (nginx et njs réels, trois services factices) sans jeton, avec treize sortes de faux jetons, puis avec chaque rôle.

## 1. Fichiers

| Fichier | Rôle |
|---|---|
| `nginx.conf` | Cadre commun : variables d'environnement lues, limites, pages d'erreur au format `Problem`, sondes. Monté sur `/etc/nginx/nginx.conf` |
| `routes.conf` | **Généré** depuis `contracts/openapi/` : un `location` par chemin (service, méthodes autorisées) |
| `routes.json` | **Généré** : le rôle exigé par (méthode, chemin), lu par `auth.js` |
| `protected.conf`, `public.conf`, `upstream.conf` | Ce que reçoit une route protégée, une route publique, et l'envoi vers un service (en-têtes transmis) |
| `auth.js` | njs : vérification du jeton et du rôle, CORS, en-têtes de sécurité, corrélation |
| `tests/` | `test_gateway.py` (passerelle réelle, Docker), `auth.test.mjs` (Node, sans Docker) |

Le dossier est monté en lecture seule sur `/etc/nginx/gateway`. **Aucun secret n'y est écrit** (section 6).

## 2. Routes : générées depuis les contrats

`python scripts/dev/gateway_routes.py` (ou `make gateway-routes`) lit les contrats et écrit `routes.conf` et `routes.json` ; `--check` échoue si les fichiers sont périmés (test `scripts/dev/test_gateway_routes.py`, dans la CI). Pourquoi générer : le service, les méthodes et le rôle exigé de chaque route sont **déjà** dans les contrats (`x-required-role`, `security: []`) ; les recopier à la main prépare le jour où un contrat change et où la passerelle laisse passer une route sans le rôle voulu.

| Chemin | Service | Rôle exigé |
|---|---|---|
| `GET /api/v1/health` | `traitement` (provisoire, jusqu'au service API métier) | publique |
| `POST /api/v1/auth/login` | `traitement` | publique (limite propre, section 4) |
| `GET /api/v1/auth/me` | `traitement` | `viewer` |
| `/api/v1/users`, `/users/{id}` | `traitement` | `admin` |
| `/api/v1/intersections`, `/road-segments`, `/indicators`, `/forecasts`, `/reports` (et sous-chemins du contrat) | `traitement` | `viewer` |
| `/api/v1/alerts`, `/alert-rules`, `/events/stream` (SSE) | `alerte` | `viewer` ; `operator` pour acquitter et résoudre ; `admin` pour régler une règle |
| `/api/v1/signals`, `/signals/{id}`, `/signals/{id}/commands` | `reponse` | `viewer` ; `operator` pour commander |
| `/api/v1/measurements` | refusé (404) | dépôt interne : le simulateur parle à la collecte, pas à la passerelle |
| `/health` | la passerelle elle-même | publique |
| le reste | 404 `Problem` | |

Règles : un **chemin** qui n'est pas dans les contrats est un 404 ; une **méthode** que le contrat ne prévoit pas est un 405 avec `Allow` ; `OPTIONS` (pré-vérification CORS) est traité avant l'authentification. Le rôle est décidé sur le chemin **brut**, le routage sur le chemin normalisé : pour qu'ils ne divergent jamais, la passerelle refuse (`400`) tout chemin qui n'est pas « simple » (lettres, chiffres, `_`, `-`, `.`, `/` ; ni `//`, ni `/.`, ni `/..`, ni `%2e`).

## 3. Authentification et rôles

`auth.js` valide le jeton comme le font les services (`services/*/app/core/auth.py`) : JWT signé **HS256**, algorithme **fixé** (jamais lu dans le jeton : `none`, HS384, RS256 sont refusés), revendications `sub`, `role`, `iat`, `exp` obligatoires et de bon type, expiration contrôlée, émission dans le futur refusée au-delà de 30 s, jeton de 4 096 caractères au plus. La signature est comparée à durée constante. Le rôle est comparé à celui de `routes.json` (`viewer` < `operator` < `admin`).

| Cas | Réponse |
|---|---|
| Pas d'en-tête `Authorization: Bearer …`, autre schéma, jeton illisible, mal signé, expiré, incomplet, rôle inconnu | **401** `UNAUTHENTICATED` + `WWW-Authenticate: Bearer`, jamais la raison |
| Jeton valide, rôle trop faible | **403** `FORBIDDEN` |
| Clé de signature absente, de moins de 32 caractères, ou valeur d'exemple hors local | **503** `UPSTREAM_UNAVAILABLE` pour toute route protégée : jamais un accès accordé par défaut. La sonde et les routes publiques répondent |
| Jeton valide | La requête part au service avec `Authorization` (les services le contrôlent aussi) et `X-User-Id` / `X-User-Role` posés par la passerelle ; ceux écrits par le client sont écrasés |

Le jeton n'est accepté que dans l'en-tête `Authorization` : jamais dans l'adresse (le flux SSE du tableau de bord est lu avec `fetch`, qui peut envoyer l'en-tête).

**Ce que la passerelle ne sait pas** : si le compte est encore actif. Le jeton prouve qui appelle ; seule l'API métier relit le compte en base. Un compte désactivé reste donc accepté par la passerelle jusqu'à l'expiration du jeton (30 minutes), mais refusé par `traitement` (qui relit le compte à chaque requête) ; `alerte` et `reponse` ne relisent pas le compte. Le rôle du jeton est celui de la connexion, comme dans ces deux services.

## 4. Limitation de débit

| Limite | Valeur | Réglage |
|---|---|---|
| Toutes les routes, par adresse | 20 requêtes par seconde, rafale de 40 | `limit_req_zone … zone=api` dans `nginx.conf` |
| `POST /api/v1/auth/login`, par adresse | 10 par minute, rafale de 5 (en plus de celle du service : 10 essais par minute et 5 échecs par identifiant, BE-08) | `zone=login` |
| Flux SSE ouverts en même temps, par adresse | 10 | `limit_conn_zone … zone=streams` |
| Corps de requête | 1 Mo | `client_max_body_size` |

Au-delà : `429` `RATE_LIMITED` au format `Problem` avec `Retry-After` (1 s, 6 s pour la connexion). **Adresse du client** : le front-end (nginx) envoie l'adresse du navigateur dans `X-Forwarded-For` ; la passerelle ne la croit que d'un relais du réseau privé (`set_real_ip_from`, `real_ip_recursive off`).

## 5. CORS et en-têtes de sécurité

Tout est posé par `auth.js` sur **toutes** les réponses, erreurs de la passerelle comprises, après avoir **effacé** ceux des services : la passerelle est l'unique source de ces en-têtes (pas de doublon, pas de `*` venu d'un service).

| En-tête | Valeur |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` |
| `Cache-Control` | `no-store` sur `/api/v1/auth/*` et le flux SSE |
| `Strict-Transport-Security` | seulement si `X-Forwarded-Proto: https` (le point qui termine TLS) : en local il n'y a pas de TLS |
| `X-Correlation-ID` | repris de la requête s'il est sobre (`[A-Za-z0-9._:-]`, 100 au plus), généré sinon ; transmis aux services |
| `Server` | sans version de nginx |

**CORS** : origines exactes de `CORS_ALLOWED_ORIGINS` (`schéma://hôte[:port]`, jamais `*`, jamais de chemin ; fermé si la liste est vide). Méthodes `GET, POST, PATCH, OPTIONS` ; en-têtes `Authorization, Content-Type, X-Correlation-ID` ; lisibles par le script : `X-Correlation-ID, Retry-After, Allow, WWW-Authenticate` ; pré-vérification mise en cache 600 s ; **jamais de cookie** (`Access-Control-Allow-Credentials` n'est pas envoyé). La pré-vérification d'une origine autorisée passe **sans jeton** ; celle d'une origine inconnue est refusée (`403`). CORS protège le navigateur, pas l'API : il ne remplace ni l'authentification ni la limite de débit.

## 6. Secrets

| Secret | D'où il vient | Où il n'est jamais |
|---|---|---|
| `JWT_SECRET` | L'environnement du conteneur (`.env`, généré par `dev.py init-env`, passé par `docker-compose.yml` sous la forme `${JWT_SECRET:-}`) ; nginx le déclare par `env JWT_SECRET;` et `auth.js` le lit par `process.env` | Dans `gateway/` (fichiers de configuration, script, générés, tests), dans le journal d'accès (`$uri` et jamais `$request_uri` ni `Authorization`), dans un message d'erreur de njs |

La clé doit faire 32 caractères au moins ; la valeur d'exemple de `.env.example` n'est tolérée que si `ENVIRONMENT=local`. Tests : `test_gateway.py` cherche la clé et les jetons dans les journaux du conteneur (absents), `test_gateway_routes.py` interdit toute valeur de secret ou tout jeton dans le dossier. En déploiement : même variable, fournie par le gestionnaire de secrets ([secrets](../docs/04-devsecops/secrets.md)).

## 7. Tests et commandes

| Action | Commande |
|---|---|
| Passerelle réelle devant trois services factices (Docker requis) | `python -m unittest discover -s gateway/tests -p "test_gateway.py" -v` ou `make test-gateway` |
| Logique de `auth.js` sous Node, sans Docker | `node --test gateway/tests/auth.test.mjs` ou `make test-gateway-unit` |
| Routes générées à jour, configuration sans trou (sans Docker, dans la CI) | `python -m unittest discover -s scripts/dev -p "test_gateway_routes.py"` |
| Regénérer les routes après un changement de contrat | `python scripts/dev/gateway_routes.py` ou `make gateway-routes` |
| Contrôle de la syntaxe | `docker run --rm --add-host traitement:127.0.0.1 --add-host alerte:127.0.0.1 --add-host reponse:127.0.0.1 -e JWT_SECRET=x -e ENVIRONMENT=local -v "$PWD/gateway/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$PWD/gateway:/etc/nginx/gateway:ro" nginxinc/nginx-unprivileged:1.30-alpine nginx -t` |

## 8. Limites assumées

| Sujet | Position actuelle |
|---|---|
| Clé partagée (HS256) | La passerelle, `traitement`, `alerte` et `reponse` ont la même clé : qui la connaît peut émettre un jeton. Les services gardent leur propre contrôle (défense en profondeur). Lever cela demande une signature asymétrique (la passerelle n'aurait que la clé publique) : non fait |
| Compte désactivé | Voir la section 3 : refusé par `traitement`, pas par la passerelle |
| Un jeton volé | Pas de liste de révocation : valable 30 minutes tant que le compte est actif |
| Adresse du client en local | Un appel venu de l'hôte arrive de l'adresse du réseau Docker, qui est « de confiance » : en local il peut écrire lui-même `X-Forwarded-For` et changer d'adresse pour la limite. Ne publier que la passerelle (et jamais les ports des services) hors du poste de développement |
| Ports des services | `docker-compose.yml` publie encore les ports de chaque service sur `127.0.0.1` pour le développement : un appel direct contourne la passerelle. Hors local, ne publier que la passerelle |
| `/docs` et `/redoc` des services | Non exposées par la passerelle (aucune route) |
| Limite par adresse | Compteurs en mémoire de nginx : un redémarrage les remet à zéro |
| TLS | Aucun en local ; `Strict-Transport-Security` est posé derrière un point qui le termine |
| Exécution sous Linux, CI | Épreuve exécutée sous Windows. `gateway/tests/` n'est pas lancé par la CI (Docker et Node) ; `test_gateway_routes.py` l'est |

## 9. Preuves

| Niveau | Fichier | Résultat | Ce qu'il prouve |
|---|---|---|---|
| Passerelle réelle (nginx et njs, image réelle, trois services factices), Docker | `tests/test_gateway.py` | **28 tests** | **Chaque route des contrats** : sans jeton valide, 401 (13 sortes de faux jetons : absent, illisible, autre clé, expiré, émis dans le futur, algorithme `none` ou HS384, revendication manquante, rôle inconnu…) ; rôle trop faible : 403 ; bon rôle : le service reçoit la requête avec l'identité vérifiée (celle écrite par le client est écrasée) ; routes publiques : la sonde et la connexion seulement ; chemin truqué : 400 ; route ou méthode inconnue : 404, 405 ; en-têtes uniques et ceux de la passerelle (le `*` et le `SAMEORIGIN` d'un service sont effacés) ; CORS (origine autorisée, refusée, pré-vérification sans jeton, jamais de cookie) ; limite de débit en 429 (API et connexion) ; corrélation dangereuse remplacée ; **aucun jeton ni clé dans les journaux** ; sans clé utilisable (absente, courte, d'exemple hors local) tout le protégé est refusé (503) ; jeton émis comme le fait l'API métier accepté ; **à travers le nginx du front-end** (`frontend/nginx.conf`) : en-têtes toujours en un seul exemplaire, jeton transmis, adresse du navigateur reçue par la passerelle, flux sans mise en cache |
| Logique de `auth.js`, Node | `tests/auth.test.mjs` | **30 tests** | Décodage, expiration à la seconde, signature comparée en entier, base64url strict, algorithme fixé, rôles, clé, table des routes, CORS, en-têtes, gestionnaires. **42 mutations** du code (comparaison inversée, contrôle retiré, algorithme laissé libre…) : 42 détectées, dont quatre ont demandé un test de plus (jeton démesuré, quatrième morceau, corps signé qui n'est pas un objet, signature en base64 standard) |
| Routes et configuration, sans Docker (dans la CI) | `scripts/dev/test_gateway_routes.py`, `test_compose.py` | **14 + 49 tests** | Fichiers générés identiques à ceux que produit le script ; chaque opération des contrats a son rôle (sonde et connexion publiques, rien d'autre) ; chaque `location` est protégée ou déclarée publique, une seule fois ; journal d'accès sans jeton ni requête ; aucune valeur de secret dans `gateway/` |
| **Images réelles** (traitement, alerte, reponse, passerelle) | épreuve du 12/11/2026 | critère atteint | Sans jeton valide, 401 pour chacun des trois services (4 sortes de faux jetons chacun) ; 403 pour un rôle trop faible ; avec un jeton valide, la requête atteint le vrai service (200 de `reponse`, 202 d'une commande qui porte l'identité du jeton, 503 d'`alerte` sans PostgreSQL) ; un appel direct à un service sans jeton est refusé aussi ; en-têtes et CORS uniques ; 13 appels sur 100 limités en 429 ; ni clé ni jeton dans les journaux ni dans la configuration montée |

**Non vérifié** : Linux et la CI GitHub (`gateway/tests/` n'est pas lancé par la CI) ; SonarQube ; la chaîne complète avec PostgreSQL, MongoDB et Kafka (l'épreuve en images réelles n'a pas ces bases : les routes qui en dépendent répondent 503 dans le service) ; le jeton émis par le vrai `create_access_token` de `services/traitement` n'a pu être essayé sous Windows (SQLAlchemy bloqué par la politique du poste) : le test utilise alors PyJWT avec la même charge utile ; le tableau de bord n'a pas été rejoué contre cette passerelle (le nginx du front-end, lui, est éprouvé par un test : section 9, premier tableau) ; le flux SSE n'a pas été éprouvé de bout en bout (seule sa configuration l'est : sans tampon, limite de flux, `no-store`).

