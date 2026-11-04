# Sécurité applicative du back-end (BE-08)

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 04/11/2026
Issue de suivi : BE-08 (#68)
Statut : à valider par les deux membres (relecture de la pull request)

Critère d'acceptation : **aucun secret en clair dans le dépôt, les variables ou les journaux** (EXG-NFR-11). Preuves : résultat de gitleaks et de Snyk (section 8).

Abréviations : **CORS** (Cross-Origin Resource Sharing, partage des ressources entre origines), **CSP** (Content Security Policy, politique de sécurité du contenu), **ECS** (Elastic Container Service), **IAM** (Identity and Access Management), **JWT** (JSON Web Token), **KMS** (Key Management Service), **SSM** (Systems Manager), **TLS** (Transport Layer Security).

## 1. Ce que fait BE-08

| Besoin de l'issue | Mécanisme | Code | Tests |
|---|---|---|---|
| CORS restreint | Origines exactes listées, méthodes et en-têtes limités à ceux de l'API, pas de cookies ; fermé par défaut | `app/core/cors.py`, `app/core/config.py` | `tests/unit/test_cors.py` |
| En-têtes de sécurité | `nosniff`, `X-Frame-Options`, `Referrer-Policy`, politique de contenu, `no-store` sur l'authentification | `app/core/headers.py` | `tests/unit/test_security_headers.py` |
| Limitation de débit sur la connexion | Deux limites (adresse du client, échecs par identifiant), `429` avec `Retry-After` | `app/core/ratelimit.py`, `app/api/v1/auth.py`, `app/api/deps.py` | `tests/unit/test_ratelimit.py`, `tests/unit/test_login_limit.py`, `tests/contract/test_errors_contract.py` |
| Secrets lus depuis l'environnement | `Settings` (`SecretStr`), valeur d'exemple refusée hors local, aucune valeur par défaut, `.env` généré | `app/core/config.py`, `scripts/dev/dev.py` (`init-env`) | `tests/unit/test_settings.py`, `scripts/dev/test_secrets_environnement.py` |
| Aucun secret dans les journaux | Le code n'en écrit pas ; un filet masque ce qui échapperait | `app/core/redaction.py` | `tests/unit/test_secrets_in_logs.py` |
| Secrets Manager documenté | Correspondance variable par variable avec AWS, rien de créé | section 6 | `scripts/dev/test_secrets_environnement.py` (tâches ECS) |

Ces mécanismes sont dans le service `services/traitement`, qui porte l'API métier (authentification, comptes) et l'API des indicateurs. Les services `collecte`, `alerte` et `reponse` sont des squelettes sans API publique : ils recevront ces mécanismes avec leurs routes, ou la passerelle (MS-13) les portera pour tous.

## 2. CORS restreint

CORS est une protection **du navigateur** : il empêche le script d'une page de lire la réponse d'une autre origine, sauf si le serveur l'autorise. Le serveur ne peut pas l'imposer à un client qui n'est pas un navigateur (curl, un autre service) : CORS ne remplace ni l'authentification ni la limitation de débit.

| Règle | Valeur |
|---|---|
| Origines autorisées | `CORS_ALLOWED_ORIGINS`, séparées par des virgules, chacune `schéma://hôte[:port]` ; **jamais `*`**, jamais de chemin (refusé au démarrage) |
| Par défaut | Vide : le middleware n'est pas monté, aucune origine n'est autorisée. `.env.example` autorise `http://localhost:8080`, `http://127.0.0.1:8080` et `http://localhost:5173` (front-end local) |
| Méthodes | `GET`, `POST`, les seules des routes publiées. Un test échoue si une route utilise une autre méthode : il faut alors décider ici |
| En-têtes de requête | `Authorization`, `Content-Type`, `X-Correlation-ID` |
| En-têtes de réponse lisibles | `X-Correlation-ID`, `Retry-After`, `Allow`, `Deprecation`, `Sunset` |
| Cookies | Aucun : `Access-Control-Allow-Credentials` n'est jamais envoyé ; le jeton voyage dans `Authorization` |
| Pré-vérification (`OPTIONS`) | Mise en cache 10 minutes |
| Erreurs | Une réponse `401`, `404`, `422` ou `429` à une origine autorisée porte les en-têtes CORS : le script peut lire le `Problem` et `Retry-After` |

Une origine non autorisée reçoit la réponse **sans** `Access-Control-Allow-Origin`. Sa pré-vérification est refusée par `400 Disallowed CORS origin` (ou `Disallowed CORS method`) : c'est la réponse de Starlette, en texte brut, que seul un navigateur lit. C'est la seule réponse de l'API qui n'est pas un `Problem`.

Le front-end du dépôt appelle l'API par **la même origine** (proxy de Vite en développement, proxy nginx dans l'image) : CORS ne lui sert pas. Il sert à un futur front-end servi d'une autre adresse.

## 3. En-têtes de sécurité

Posés sur toutes les réponses, erreurs et 500 compris, par un middleware placé à l'extérieur des autres.

| En-tête | Valeur | Effet |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Le navigateur n'interprète pas un JSON comme un script |
| `X-Frame-Options` | `DENY` | Aucun affichage dans un cadre |
| `Referrer-Policy` | `no-referrer` | L'adresse de la page appelante n'est pas transmise |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` | Une réponse de l'API ne charge rien. Absente de `/docs` et `/redoc` (elles chargent leurs scripts depuis un CDN) |
| `Cache-Control` | `no-store` sur `/api/v1/auth/` | Ni jeton ni identité dans un cache |

Une valeur déjà posée par une route n'est jamais remplacée.

**`Strict-Transport-Security` n'est pas posé par le service** : il parle HTTP à son relais ; l'en-tête appartient au point qui termine TLS (équilibreur de charge, CDN, passerelle). En local il n'y a pas de TLS : l'envoyer sur HTTP n'aurait aucun effet. Reste à poser au déploiement.

## 4. Limitation de débit de la connexion

`POST /api/v1/auth/login` est la seule route publique qui accepte un mot de passe : un attaquant peut en essayer des milliers. Deux limites, parce qu'aucune ne suffit seule.

| Limite | Ce qu'elle arrête | Valeur par défaut | Réglage |
|---|---|---|---|
| Par adresse du client | Celui qui essaie beaucoup de comptes depuis un poste (bourrage d'identifiants) | 10 essais par minute, tous comptes confondus | `LOGIN_ATTEMPTS_PER_MINUTE` |
| Par identifiant | Celui qui s'acharne sur un compte depuis plusieurs adresses | 5 échecs sur 15 minutes, puis refus (même avec le bon mot de passe) | `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_S` |

Comportement :

- au-delà, `429` au format `Problem` (`code: RATE_LIMITED`) avec `Retry-After` (secondes), conforme au contrat (`common.yaml`, `api-metier.openapi.yaml`) ;
- **un identifiant inexistant est limité comme un compte réel** : la réponse `429` (statut, code, détail, délai) est identique, elle ne dit pas si le compte existe ;
- un succès remet à zéro le compteur d'échecs de l'identifiant ; un refus de la limite n'est pas compté (il ne prolonge pas l'attente) ;
- une requête que la validation refuse (`422`) n'est pas comptée ;
- la casse et les espaces autour de l'identifiant n'y changent rien ;
- la limite est vérifiée **avant** le calcul argon2id : un refus ne coûte rien au serveur ;
- chaque refus est audité (`denied`, acteur `anonymous`) et journalisé sans identifiant ni adresse (`connexion limitée`, durée d'attente).

### Adresse du client

Derrière un relais, l'adresse de la connexion est celle du relais. `TRUSTED_PROXY_HOPS` dit combien de relais de confiance précèdent le service : à **0** (défaut), `X-Forwarded-For` est ignoré et un client ne peut pas falsifier son adresse ; à **N**, l'adresse retenue est la N-ième en partant de la **droite** (chaque relais ajoute l'adresse de son interlocuteur à droite ; ce qui est à gauche vient du client). `docker-compose.yml` met 1 : la passerelle nginx réécrit `X-Forwarded-For` avec l'adresse qu'elle a vue. Un client IPv6 est identifié par son réseau /64.

### Limites assumées

| Sujet | Position actuelle | Suite |
|---|---|---|
| État en mémoire | Le compteur est dans le processus : un redémarrage le remet à zéro, et N processus ou N répliques multiplient les essais permis par N | Compteur partagé (magasin externe) ou limite à la passerelle / au pare-feu applicatif quand le service est répliqué |
| Blocage d'un compte par un tiers | Quelqu'un qui connaît un identifiant peut le bloquer 15 minutes en échouant 5 fois. Contre-mesure : la limite par adresse freine cet acharnement, et la durée est courte | Valeurs à ajuster selon l'usage réel |
| Adresse réelle derrière Docker Desktop | Sous Windows et macOS, les connexions venues de l'hôte peuvent toutes arriver avec la même adresse interne : la limite par adresse serait alors commune à tous les appels de l'hôte (**non vérifié** : l'essai de bout en bout lance `uvicorn` hors Docker). La limite par identifiant n'est pas touchée | Sans effet attendu sous Linux et en production, à constater sur la pile Compose |
| Accès direct au service | Le port 8002 du traitement est publié sur `127.0.0.1` : un appel direct peut écrire un `X-Forwarded-For` falsifié et contourner la limite par adresse (pas celle par identifiant) | Ne publier que la passerelle, hors local |
| Mémoire | Bornée à 10 000 clés par limite ; au-delà les plus anciennes sont oubliées | |
| Autres routes | Seule la connexion est limitée (périmètre de l'issue) | Limite générale à la passerelle (MS-13) |

## 5. Secrets lus depuis l'environnement

| Règle | Mise en œuvre | Preuve |
|---|---|---|
| Jamais dans le dépôt | `.env` et `.env.*` sont ignorés par Git ; seul `.env.example` est suivi, avec la valeur d'exemple `change-me-local` | `test_secrets_environnement.py` : seul `.env.example` est suivi, variantes ignorées, aucune clé ni certificat suivi |
| `.env` généré | `dev.py init-env` remplace chaque valeur d'exemple par `secrets.token_urlsafe` (24 octets, 48 pour `JWT_SECRET`), écrit le fichier en lecture réservée (0600), n'affiche aucune valeur | `test_secrets_environnement.py` : aucune valeur d'exemple ne survit, longueurs, valeurs différentes à chaque génération et entre secrets |
| Aucune valeur par défaut dans le code | `jwt_secret`, `app_database_url`, `postgres_url`, `audit_mongo_url` valent `None` sans variable : l'authentification répond `503`, l'audit s'arrête avec un avertissement | `test_settings.py` |
| Valeur d'exemple refusée hors local | Si `ENVIRONMENT` n'est pas `local`, un secret qui contient `change-me-local` empêche le démarrage | `test_settings.py` (4 secrets, 4 environnements) |
| Un secret refusé n'est pas recopié | `hide_input_in_errors` : le message de démarrage ne contient pas la valeur refusée (avant BE-08, un `JWT_SECRET` trop court était recopié dans l'erreur) | `test_settings.py` |
| Jamais affiché | `SecretStr` : `repr`, `str` et la sérialisation JSON de la configuration masquent la valeur | `test_settings.py` |
| Docker Compose ne contient aucune valeur | `docker-compose.yml`, les Dockerfile, les workflows et les tâches ECS n'ont que des références (`${NOM}`, `secrets.NOM`, `valueFrom`) ; aucune adresse de connexion n'y porte un mot de passe écrit | `test_secrets_environnement.py` |
| Les tâches ECS ne mettent pas de secret dans `environment` | Un secret passe par `secrets[].valueFrom` (SSM ou Secrets Manager) | `test_secrets_environnement.py` |

### Dans les journaux

Deux niveaux, testés séparément (`tests/unit/test_secrets_in_logs.py`, 27 tests, valeurs générées à l'exécution) :

1. **La discipline du code.** Sur chaque parcours (connexion réussie, refusée, limitée, mot de passe refusé par la validation, jeton faux, jeton collé dans l'adresse, base en panne, erreur imprévue), les lignes que le code écrit, **sans** le filet, ne contiennent ni secret de configuration, ni mot de passe, ni jeton, ni empreinte argon2. Le journal d'audit non plus. Les gestionnaires d'erreurs écrivent le **type** de l'erreur, jamais son message (celui d'une bibliothèque de base de données peut contenir l'adresse de connexion).
2. **Le filet** (`app/core/redaction.py`). Une ligne qui contiendrait un secret malgré tout sort masquée (`***`) : valeur de toute variable d'environnement dont le nom dit « secret », secrets de la configuration y compris lus dans `.env`, mot de passe de toute adresse de connexion, `Bearer <jeton>`, tout jeton de forme JWT. Il agit sur la ligne déjà sérialisée : message, champs et trace d'exécution. Il couvre les formes brute, JSON (guillemets, barres inverses, accents) et encodée pour une adresse. Il ne remplace pas la discipline : une valeur de moins de 8 caractères n'est pas cherchée.

Un constat de la rédaction des tests : le client de test (`httpx`) journalise l'adresse appelée, query string comprise. Le service, lui, n'écrit **jamais** la query string (`CorrelationMiddleware`) ; le test le prouve en écartant les journaux du client.

### Ce qui n'est pas couvert

| Sujet | Position |
|---|---|
| Variables d'environnement d'un conteneur | `docker compose` les place dans l'environnement du conteneur : `docker inspect` les montre à qui a accès au démon Docker du poste. Acceptable en local (poste du membre), pas en production, où ECS les lit dans un gestionnaire de secrets au démarrage |
| Mémoire du processus | Le secret y est en clair, comme pour tout programme |

## 6. Secrets Manager (documenté, non créé)

Aucun compte AWS n'existe (exécution locale d'abord, [ADR-023](../01-architecture/adr/ADR-023-execution-locale-d-abord.md)) : **rien de ce qui suit n'a été créé ni testé en ligne**. Le code ne change pas entre les deux mondes : il lit des variables d'environnement. Seule la **source** de ces variables change ([ADR-025](../01-architecture/adr/ADR-025-equivalents-locaux-des-services-aws.md)).

| | Local (aujourd'hui) | AWS (à l'ouverture du compte) |
|---|---|---|
| Source des valeurs | `.env` généré par `dev.py init-env`, ignoré par Git | AWS Secrets Manager ou SSM Parameter Store (type `SecureString`) |
| Qui injecte | `docker compose` (`environment:`) | ECS au démarrage de la tâche : `secrets[].valueFrom` de la définition de tâche |
| Qui lit | Le processus du service (variables d'environnement) | Idem : le service ne contient aucun SDK AWS (EXG-NFR-09) |
| Droits | Fichier en lecture réservée (0600) | Le **rôle d'exécution** de la tâche (`novaria-dev-ecs-execution`), pas le rôle de la tâche |

### Correspondance variable par variable

| Variable | Rôle | Emplacement AWS prévu | Dans `taskdef-backend.json` aujourd'hui |
|---|---|---|---|
| `JWT_SECRET` | Signature des jetons | Paramètre `/novaria/dev/jwt-secret` (ou secret du même nom) | Oui |
| `POSTGRES_URL` | Entrepôt `dwh`, compte `svc_traitement` | `/novaria/dev/postgres-url` | Oui |
| `MONGO_URL` | MongoDB, compte du traitement | `/novaria/dev/mongo-url` | Oui |
| `APP_DATABASE_URL` | Base métier, schéma `app`, compte `svc_app` | `/novaria/dev/app-database-url` | **Non** : à ajouter |
| `AUDIT_MONGO_URL` | Audit et compteurs, compte `svc_backend` | `/novaria/dev/audit-mongo-url` | **Non** : à ajouter |
| `ENVIRONMENT`, `MONGO_DB`, `CORS_ALLOWED_ORIGINS`, `LOGIN_*`, `TRUSTED_PROXY_HOPS` | Réglages, **pas des secrets** | `environment` de la tâche | Seuls `ENVIRONMENT` et `MONGO_DB` : à compléter (en particulier `ENVIRONMENT` ne doit pas rester `local` si les secrets sont réels) |

Deux écarts à traiter au moment du déploiement (CLD), non corrigés ici parce que `infra/` est inactif et que rien ne peut être vérifié sans compte : `APP_DATABASE_URL` et `AUDIT_MONGO_URL` manquent à la définition de tâche (ajoutés par BE-03 et BE-05 au service), et les réglages de BE-08 n'y figurent pas.

### Choix et règles à décider au déploiement

| Sujet | Recommandation |
|---|---|
| Secrets Manager ou SSM `SecureString` | Les deux s'injectent de la même façon dans ECS. Secrets Manager apporte la **rotation automatique** (utile pour les mots de passe de base) et des versions ; SSM suffit pour des valeurs qui changent rarement. Choix à faire à l'ouverture du compte, tarifs à vérifier alors |
| Droits du rôle d'exécution | Lecture seule (`ssm:GetParameters` ou `secretsmanager:GetSecretValue`) sur les seuls secrets de l'environnement, plus `kms:Decrypt` si la clé de chiffrement est gérée par le projet ; aucun joker `*` |
| Chiffrement | Clé KMS gérée par AWS ou propre au projet ; journaliser l'accès (CloudTrail) |
| Mots de passe de base | Un compte par service, droits minimaux (ADR-024) : déjà le cas en local, à reproduire dans RDS et Atlas ; rotation par Secrets Manager |
| `JWT_SECRET` | Pas de rotation sans interruption : le service ne vérifie qu'une clé. Changer la valeur invalide les jetons émis (30 minutes de vie). Passage à une clé asymétrique si la passerelle contrôle le jeton (voir `authentification.md`) |
| Journaux CloudWatch | Le filet de masquage s'applique avant l'écriture : ce qui part vers `awslogs` est déjà masqué |
| Secrets de la CI | Inchangés : GitHub Secrets (`SNYK_TOKEN`, `SONAR_TOKEN`), inventoriés dans [secrets.md](secrets.md) ; jamais copiés dans AWS |

## 7. Rejouer les preuves

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Tests du service | `cd services/traitement && pytest` | `cd services\traitement; pytest` |
| Contrôle des fichiers de configuration | `python3 -m unittest scripts/dev/test_secrets_environnement.py` | `py -3 -m unittest scripts/dev/test_secrets_environnement.py` |
| Toute la suite des scripts | `python3 -m unittest discover -s scripts/dev` | `py -3 -m unittest discover -s scripts/dev` |
| Fuites dans l'historique (gitleaks) | `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest detect --source /repo --redact --verbose` | `docker run --rm -v "${PWD}:/repo" zricethezav/gitleaks:latest detect --source /repo --redact --verbose` |
| Failles de dépendances (Snyk) | `snyk test --file=services/traitement/requirements.txt --package-manager=pip --severity-threshold=high` (jeton requis : `snyk auth`) | idem |
| Code (Snyk Code) | `snyk code test --severity-threshold=high` | idem |

## 8. Preuves

### 8.1 Tests

| Preuve | Résultat (04/11/2026, poste Windows) |
|---|---|
| Service traitement (sans base, comme la CI) | 1 085 tests réussis, 83 ignorés (PostgreSQL et MongoDB absents) ; couverture 99,34 % (barrière de 70 % de BE-07 atteinte) ; fichiers nouveaux (`ratelimit`, `redaction`, `headers`, `cors`) à 100 % |
| Scripts du dépôt | 417 tests, dont 16 de `test_secrets_environnement.py` |
| Contrôle par mutations | 49 défauts introduits volontairement dans le code de sécurité (limiteur, adresse du client, en-têtes, CORS, configuration, journalisation, masquage) : 42 détectés d'emblée ; 7 survivants analysés : 2 étaient du code mort (un `max(1, …)` redondant, une variante JSON inutile), supprimé ; 5 révélaient un test manquant ou circulaire (arrondi du délai, liste d'en-têtes comparée à elle-même, filet installé au démarrage, `Bearer` opaque, forme encodée), corrigés ; les 8 mutations rejouées sont toutes détectées |
| `ruff format` et `ruff check` | Sans remarque |

### 8.2 Essai de bout en bout

Vrai serveur `uvicorn`, vrais PostgreSQL 16 et MongoDB 7 dans un projet Compose jetable (supprimé ensuite), compte réel créé, appels HTTP réels, puis lecture du journal du serveur. Le relais de confiance est simulé par `X-Forwarded-For` (comme la passerelle le fait) pour séparer les limites.

```text
Projet Compose jetable : novaria-be08-53b00b (PostgreSQL :61725, MongoDB :61726), uvicorn :61727
alembic upgrade head -> code 0
compte alice créé

=== 1. En-têtes de sécurité (GET /api/v1/health)
  x-content-type-options: nosniff
  x-frame-options: DENY
  referrer-policy: no-referrer
  content-security-policy: default-src 'none'; frame-ancestors 'none'

=== 2. CORS
  Origin autorisée   -> 200, access-control-allow-origin=http://localhost:8080, credentials=None
  Origin inconnue    -> 200, access-control-allow-origin=None
  Pré-vérification OK -> 200, methods=GET, POST, headers=Accept, Accept-Language, Authorization, Content-Language, Content-Type, X-Correlation-ID, max-age=600
  Pré-vérification pirate -> 400 'Disallowed CORS origin'
  Pré-vérification DELETE -> 400 'Disallowed CORS method'

=== 3. Connexion réelle (compte dans PostgreSQL)
  bon mot de passe   -> 200, cache-control=no-store, jeton émis=True

=== 4. Limitation par identifiant : 5 échecs, puis blocage même avec le bon mot de passe et une autre adresse
  échec 1 (adresse .11): 401 INVALID_CREDENTIALS
  échec 2 (adresse .11): 401 INVALID_CREDENTIALS
  échec 3 (adresse .11): 401 INVALID_CREDENTIALS
  échec 4 (adresse .11): 401 INVALID_CREDENTIALS
  échec 5 (adresse .11): 401 INVALID_CREDENTIALS
  6e essai, BON mot de passe, adresse .12 -> 429 RATE_LIMITED retry-after=900 content-type=application/problem+json
  identifiant INEXISTANT, 5 échecs puis le 6e depuis une autre adresse -> 429 RATE_LIMITED retry-after=900
  même détail que pour un compte réel : True (l'existence du compte n'est pas révélée)

=== 5. Limitation par adresse : 10 essais par minute, 12 comptes différents depuis la même adresse (.20)
  statuts : [401, 401, 401, 401, 401, 401, 401, 401, 401, 401, 429, 429]
  retry-after du dernier = 59 s ; une autre adresse (.21) n'est pas touchée -> 401
  adresse falsifiée à gauche de X-Forwarded-For (le relais a vu .20) -> 429 (la limite suit toujours .20)

=== 6. Le journal du serveur ne contient aucun secret
  JWT_SECRET                : ABSENT
  mot de passe PostgreSQL   : ABSENT
  mot de passe MongoDB      : ABSENT
  jeton émis                : ABSENT
  mot de passe de alice     : ABSENT
  mot de passe faux         : ABSENT
  empreinte argon2          : ABSENT
  (62 lignes de journal contrôlées)
  extrait :
    {"ts": "2026-11-04T17:22:24.895Z", "level": "INFO", "service": "traitement", "logger": "app.auth", "message": "connexion refusée", "correlation_id": "1b6...
    {"ts": "2026-11-04T17:22:24.910Z", "level": "WARNING", "service": "traitement", "logger": "app.auth", "message": "connexion limitée", "correlation_id": "...
    {"ts": "2026-11-04T17:22:24.914Z", "level": "INFO", "service": "traitement", "logger": "app.access", "message": "requête traitée", "correlation_id": "1b6...
    {"ts": "2026-11-04T17:22:24.925Z", "level": "INFO", "service": "traitement", "logger": "app.access", "message": "requête traitée", "correlation_id": "9fc...

Projet novaria-be08-53b00b supprimé.
```

### 8.3 gitleaks

Commande de la CI (job `gitleaks` de `ci.yml` : `gitleaks detect --redact --verbose`), lancée sur un clone de la branche `feature/BE-08-securite-applicative` : **`no leaks found`**, 39 commits analysés (41 dans la branche), 4,50 Mo, le 04/11/2026.

Un premier passage avait signalé **une détection** (`generic-api-key`) : une valeur d'essai écrite en littéral dans un test, dans un dictionnaire dont la clé s'appelle `API_TOKEN`. Ce n'était pas un secret, mais la règle ne le sait pas. Les valeurs d'essai du test sont désormais générées à l'exécution (`secrets.token_urlsafe`) et le commit local a été corrigé avant tout envoi : **aucune entrée n'a été ajoutée à `.gitleaksignore`** et aucune règle n'est désactivée.

Le fichier `.env` local, ignoré par Git, contient les vrais mots de passe du poste : il n'est pas dans l'historique (contrôle de la section 5, `test_secrets_environnement.py`).

### 8.4 Snyk

**Non exécuté ici** : le jeton Snyk (`SNYK_TOKEN`) est un secret de la CI, détenu par Manoa Robel ; il n'a pas été demandé ni copié sur ce poste (voir [secrets.md](secrets.md)). Les jobs `snyk` (dépendances, code) et `docker` de `ci.yml` s'exécuteront sur la pull request ; leur résultat est la preuve attendue par l'issue et **reste à lire** dans l'onglet Checks.

Ce que l'on peut dire sans Snyk :
- BE-08 n'ajoute **aucune dépendance** (CORS vient de Starlette, déjà présent) : le résultat Snyk des dépendances ne peut pas changer par ce travail ;
- `pip-audit` (base d'avis de PyPA, **autre outil que Snyk**, donc non équivalent) ne trouve aucune faille connue dans les fichiers verrouillés `requirements.txt` des 5 services et de l'ETL ;
- les valeurs d'essai des tests sont générées à l'exécution : aucun littéral en forme de secret n'a été écrit (règle de gitleaks et de Snyk Code contre les secrets codés en dur).

Pour la rejouer, voir la section 7. Résultat de Manoa : [À COMPLÉTER par Manoa Robel].

## 9. Limites et points ouverts

| Sujet | Position actuelle | Suite |
|---|---|---|
| Services `collecte`, `alerte`, `reponse` | Squelettes sans API publique : CORS, en-têtes et limitation absents | Avec leurs routes, ou à la passerelle (MS-13) |
| Simulateur (`simulator/`, MS-07), API de pilotage d'un run | Sans authentification, CORS, en-têtes ni limitation de débit ; publiée sur `127.0.0.1` seulement. Protégée par : corps limité à 64 Ko, un seul run à la fois, durée (7 jours), débit et nombre d'anomalies bornés, `run_id` sans points seuls ni chemin, journal sans query string ni corps (`simulator/README.md`, section 10) | À reprendre si elle est exposée au-delà de `127.0.0.1` (passerelle, MS-13) |
| Compteur de limitation | En mémoire du processus (section 4) | Magasin partagé si le service est répliqué |
| `Strict-Transport-Security` | Appartient au point qui termine TLS | Au déploiement |
| Politique de contenu de `/docs` | Absente de `/docs` et `/redoc` | Désactiver ces pages hors local |
| Secrets Manager | Documenté, non créé ; deux variables manquent à la définition de tâche (section 6) | CLD, à l'ouverture du compte AWS |
| Révocation d'un jeton | Pas de liste de révocation | Voir `authentification.md` |
| Snyk | Non exécuté ici (section 8.4) | Lire les Checks de la pull request |
| Preuve sous Linux | [À COMPLÉTER par Manoa Robel] | |
