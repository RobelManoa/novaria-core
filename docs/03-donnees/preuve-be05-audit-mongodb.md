# Preuve BE-05 : journal d'audit et compteurs d'usage dans MongoDB

Issue BE-05 (#65). Critère : chaque appel authentifié produit une entrée d'audit. Preuve attendue : capture MongoDB. Les sorties ci-dessous sont celles du 03/11/2026. Règles et limites : [journalisation d'audit](../02-specifications/journalisation-audit.md).

## Conditions

| Élément | Valeur |
|---|---|
| Poste | Windows 11 Pro, Docker Desktop, Git Bash |
| Bases | `mongo:7` (script d'initialisation du dépôt, sans modification) et `postgres:16`, **neufs**, dans un projet Compose à part (`COMPOSE_PROJECT_NAME=novaria-be05-proof`, ports 25432 et 27218) ; les volumes habituels n'ont pas été touchés |
| Service | `uvicorn app.main:app` du dépôt (vrai serveur, vraie base d'utilisateurs, vrai MongoDB), avec `AUDIT_MONGO_URL` du compte `svc_backend` ; schéma `app` créé par `alembic upgrade head` |
| Comptes de preuve | `admin_preuve` (rôle admin) et `lecteur_preuve` (rôle viewer), créés par le service d'utilisateurs ; ni leur nom ni leur mot de passe ne doivent apparaître dans MongoDB |
| Lecture | `mongosh` dans le conteneur, **avec le compte `svc_backend`** (le même que l'application : il lit, il n'efface rien) |
| Fin de la preuve | Projet supprimé : `docker compose down -v` (aucun conteneur, volume ni réseau restant) |

## 1. Scénario joué contre le service

| N° | Appel | Réponse | Audité | Compté |
|---|---|---|---|---|
| 1 | `GET /api/v1/health` | 200 | non (sonde) | non |
| 2 | `POST /api/v1/auth/login` avec un mauvais mot de passe | 401 | oui, `anonymous`, `denied` | oui |
| 3 | `POST /api/v1/auth/login` (admin) | 200 | oui | oui |
| 4 | `POST /api/v1/auth/login` (viewer) | 200 | oui | oui |
| 5 | `GET /api/v1/auth/me` (admin) | 200 | oui | oui |
| 6 | `GET /api/v1/users` (admin) | 200 | oui | oui |
| 7 | `GET /api/v1/users` (admin) | 200 | oui | oui |
| 8 | `GET /api/v1/users` (viewer) | 403 | oui, `denied` | oui |
| 9 | `GET /api/v1/users/{id}` (admin) | 200 | oui, avec `path_params` | oui |
| 10 | `GET /api/v1/indicators` (viewer) | 200 | oui | oui |
| 11 | `GET /api/v1/users` sans jeton | 401 | **non** | oui |
| 12 | `GET /api/v1/users` avec `pas-un-jeton` | 401 | **non** | oui |
| 13 | `GET /api/v1/inconnu` (admin) | 404 | **non** (route inconnue) | oui, `UNMATCHED` |

Attendu : **9 entrées** dans `audit_logs` (appels 2 à 10) ; `usage_stats` : `GET /api/v1/users` = 5 (appels 6, 7, 8, 11, 12), `POST /api/v1/auth/login` = 3, `GET /api/v1/auth/me` = 1, `GET /api/v1/users/{user_id}` = 1, `GET /api/v1/indicators` = 1, `GET UNMATCHED` = 1, et **aucune** ligne pour la sonde.

## 2. Capture MongoDB

Sortie de `mongosh` (collections vidées avant le scénario avec le compte administrateur, pour ne compter que lui) :

```text
--- audit_logs : une entrée par appel authentifié (et par connexion) ---
{
  ts: ISODate('2026-11-03T14:27:36.703Z'),
  service: 'traitement',
  actor: 'anonymous',
  action: 'POST /api/v1/auth/login',
  outcome: 'denied',
  details: {
    status: 401,
    duration_ms: 211.8
  },
  correlation_id: '7f07955b-d0cd-4da5-b7ea-a1a9fa6342e2'
}
{
  ts: ISODate('2026-11-03T14:27:36.924Z'),
  service: 'traitement',
  actor: '67e2d36d-5358-49e3-a3bc-1088827ac591',
  action: 'POST /api/v1/auth/login',
  outcome: 'ok',
  details: {
    status: 200,
    duration_ms: 151
  },
  correlation_id: 'cffb2c4d-2a01-4c47-af01-0b6612b5e9a4'
}
{
  ts: ISODate('2026-11-03T14:27:37.089Z'),
  service: 'traitement',
  actor: '985afd7d-c29a-44c4-b5d4-0796e55c8760',
  action: 'POST /api/v1/auth/login',
  outcome: 'ok',
  details: {
    status: 200,
    duration_ms: 162
  },
  correlation_id: '90dc8d36-c0f8-4320-a22a-c5a0c893fc8e'
}
{
  ts: ISODate('2026-11-03T14:27:37.248Z'),
  service: 'traitement',
  actor: '67e2d36d-5358-49e3-a3bc-1088827ac591',
  action: 'GET /api/v1/auth/me',
  outcome: 'ok',
  details: {
    status: 200,
    duration_ms: 32.5,
    role: 'admin'
  },
  correlation_id: 'a745239f-625b-46be-84bb-5b1b2dec4275'
}
{
  ts: ISODate('2026-11-03T14:27:37.278Z'),
  service: 'traitement',
  actor: '67e2d36d-5358-49e3-a3bc-1088827ac591',
  action: 'GET /api/v1/users',
  outcome: 'ok',
  details: {
    status: 200,
    duration_ms: 31.8,
    role: 'admin'
  },
  correlation_id: '82897b06-51a5-4fb4-a420-1f30857ef2b8'
}
{
  ts: ISODate('2026-11-03T14:27:37.333Z'),
  service: 'traitement',
  actor: '67e2d36d-5358-49e3-a3bc-1088827ac591',
  action: 'GET /api/v1/users',
  outcome: 'ok',
  details: {
    status: 200,
    duration_ms: 22.1,
    role: 'admin'
  },
  correlation_id: '6646525a-ae81-451e-9731-09f525643729'
}
{
  ts: ISODate('2026-11-03T14:27:37.354Z'),
  service: 'traitement',
  actor: '985afd7d-c29a-44c4-b5d4-0796e55c8760',
  action: 'GET /api/v1/users',
  outcome: 'denied',
  details: {
    status: 403,
    duration_ms: 16,
    role: 'viewer'
  },
  correlation_id: '30df366c-805b-4ad6-b803-9af860ae98cc'
}
{
  ts: ISODate('2026-11-03T14:27:37.373Z'),
  service: 'traitement',
  actor: '67e2d36d-5358-49e3-a3bc-1088827ac591',
  action: 'GET /api/v1/users/{user_id}',
  outcome: 'ok',
  details: {
    status: 200,
    duration_ms: 25.1,
    role: 'admin',
    path_params: {
      user_id: '67e2d36d-5358-49e3-a3bc-1088827ac591'
    }
  },
  correlation_id: '41832187-57ea-4f23-b352-c99ec1e744ff'
}
{
  ts: ISODate('2026-11-03T14:27:37.396Z'),
  service: 'traitement',
  actor: '985afd7d-c29a-44c4-b5d4-0796e55c8760',
  action: 'GET /api/v1/indicators',
  outcome: 'ok',
  details: {
    status: 200,
    duration_ms: 58.2,
    role: 'viewer'
  },
  correlation_id: '2d2c2cfe-a787-4e8b-9ca3-cddb0324d489'
}
--- nombre d'entrées : 9
--- usage_stats : compteurs par point d'accès et par heure UTC ---
{
  endpoint: 'GET /api/v1/auth/me',
  bucket_start: ISODate('2026-11-03T14:00:00.000Z'),
  count: 1
}
{
  bucket_start: ISODate('2026-11-03T14:00:00.000Z'),
  endpoint: 'GET /api/v1/indicators',
  count: 1
}
{
  endpoint: 'GET /api/v1/users',
  bucket_start: ISODate('2026-11-03T14:00:00.000Z'),
  count: 5
}
{
  endpoint: 'GET /api/v1/users/{user_id}',
  bucket_start: ISODate('2026-11-03T14:00:00.000Z'),
  count: 1
}
{
  endpoint: 'GET UNMATCHED',
  bucket_start: ISODate('2026-11-03T14:00:00.000Z'),
  count: 1
}
{
  bucket_start: ISODate('2026-11-03T14:00:00.000Z'),
  endpoint: 'POST /api/v1/auth/login',
  count: 3
}
```

Lecture :

- **9 entrées**, une par appel 2 à 10, dans l'ordre. Chaque entrée dit qui (`actor` : l'identifiant du compte, ou `anonymous` pour la connexion refusée), quoi (`action` : méthode et modèle de route), quand (`ts`, UTC), avec quel résultat (`outcome`, `details.status`) et sous quel `correlation_id`.
- Le viewer refusé en 403 a son entrée (`outcome: 'denied'`, `role: 'viewer'`).
- `GET /api/v1/users/{user_id}` garde le modèle de route comme action, et l'identifiant (un UUID) dans `path_params`.
- Les appels 1, 11, 12 et 13 n'ont **pas** d'entrée, comme prévu ; les trois derniers sont dans les compteurs (`GET /api/v1/users` = 5, `GET UNMATCHED` = 1), la sonde n'y est pas.
- Recherche dans cette sortie de `eyJ` (début d'un jeton), `Bearer`, `preuve` (nom et mot de passe des comptes), `password`, `argon`, `127.0.0.1` (adresse du client), `python-urllib` (navigateur) : **0 occurrence** pour chacune.

## 3. MongoDB arrêté pendant l'usage

`docker compose stop mongo`, puis une connexion et trois appels `GET /api/v1/auth/me` avec un jeton valide :

```text
appel 1 pendant la panne : HTTP 200 en 19 ms
appel 2 pendant la panne : HTTP 200 en 14 ms
appel 3 pendant la panne : HTTP 200 en 17 ms
```

Journal du service (une ligne par entrée perdue, sans adresse de base ni message d'erreur) :

```text
{"level": "ERROR", "service": "traitement", "logger": "app.audit", "message": "écriture du journal d'audit impossible", "error": "ServerSelectionTimeoutError", "endpoint": "POST /api/v1/auth/login", "dropped": 1}
{"level": "ERROR", "service": "traitement", "logger": "app.audit", "message": "écriture du journal d'audit impossible", "error": "ServerSelectionTimeoutError", "endpoint": "GET /api/v1/auth/me", "dropped": 2}
{"level": "ERROR", "service": "traitement", "logger": "app.audit", "message": "écriture du journal d'audit impossible", "error": "ServerSelectionTimeoutError", "endpoint": "GET /api/v1/auth/me", "dropped": 3}
{"level": "ERROR", "service": "traitement", "logger": "app.audit", "message": "écriture du journal d'audit impossible", "error": "ServerSelectionTimeoutError", "endpoint": "GET /api/v1/auth/me", "dropped": 4}
```

Les quatre écritures étaient déjà en cours quand la première a échoué (attente de 2 s du serveur) : elles sont toutes comptées. Après `docker compose start mongo` et 12 secondes (la pause est de 10 s), une nouvelle connexion et trois appels : `audit_logs` passe de 9 à **13 entrées**. Les 4 nouvelles sont celles de la reprise ; les 4 de la panne sont perdues, comme annoncé à la section 4 du [document de règles](../02-specifications/journalisation-audit.md).

## 4. Tests

| Série | Résultat |
|---|---|
| Sans base (comme la CI) | 574 réussis, 77 ignorés (ceux qui demandent PostgreSQL ou MongoDB) |
| Avec PostgreSQL 16 et MongoDB 7 sous Docker | **646 réussis**, 0 ignoré, couverture 99 % ; `app/core/audit.py`, `app/services/audit.py` et `app/repositories/audit.py` à 100 % |
| `scripts/dev/test_compose.py` | 48 réussis (dont : `AUDIT_MONGO_URL` avec `svc_backend` pour le seul service de l'API métier) |

Fichiers de test :

| Fichier | Ce qu'il prouve |
|---|---|
| `tests/contract/test_audit_contract.py` | **Critère d'acceptation** : pour chaque route publiée par l'application et chaque rôle (admin, operator, viewer), un appel avec jeton valide produit **exactement une** entrée, du bon acteur, de la bonne action, du bon résultat et du bon `correlation_id` ; sans jeton valide, aucune entrée mais un compteur ; sonde et chemins inconnus ; connexions ; aucun secret ni donnée personnelle (jeton, mots de passe, noms d'utilisateur, adresse IP, navigateur, jeton collé dans l'adresse) |
| `tests/unit/test_audit.py` | Résultat selon le code HTTP, tranche d'une heure UTC, paramètres de chemin filtrés, liste fermée des champs, modèles de route, pause après échec |
| `tests/unit/test_audit_middleware.py` | Branchement ASGI : 500 enregistré si la route plante, pas d'événement pour la sonde, journal en panne sans effet sur la réponse, adresse de la base absente des journaux |
| `tests/unit/test_audit_repository.py` | Incrément atomique, nouvel essai sur doublon d'index |
| `tests/integration/test_audit_mongo.py` | Contre un vrai MongoDB : types stockés, validateur actif (contre-épreuve), compte `svc_backend` sans droit de modifier ni supprimer, 50 incréments simultanés = 50, de bout en bout application → MongoDB |

Contrôle par mutations (code d'audit cassé volontairement, à la main : aucun outil de mutation n'est installé dans le dépôt). Première série : 29 défauts, 26 détectés d'emblée. Les 3 autres : une constante inutilisée (le code mort a été supprimé), la durée de la pause de 10 s (que rien ne fixait : un test sur sa valeur a été ajouté) et un défaut mal écrit (réécrit). Rejeu : les 5 défauts restants ou nouveaux (pause, rôle absent, paramètres de chemin, fuseau horaire de la tranche, fuseau horaire de l'horodatage) sont tous détectés.

## 5. Rejouer

```text
python scripts/dev/dev.py init-env
set COMPOSE_PROJECT_NAME=novaria-be05-proof & set POSTGRES_PORT=25432 & set MONGO_PORT=27218
docker compose up -d --wait mongo postgres
cd services/traitement
set NOVARIA_TEST_MONGO_URL=mongodb://svc_backend:<MONGO_PASSWORD_BACKEND>@127.0.0.1:27218/novaria?authSource=novaria
set NOVARIA_TEST_MONGO_ADMIN_URL=mongodb://mongo_admin:<MONGO_ROOT_PASSWORD>@127.0.0.1:27218/novaria?authSource=admin
pytest tests/integration/test_audit_mongo.py
```

`NOVARIA_TEST_MONGO_ADMIN_URL` est facultative : elle sert seulement à effacer les traces que les tests laissent dans `audit_logs` (le compte `svc_backend` ne peut rien supprimer). Les compteurs sont comparés par écart, car ils sont partagés avec les autres écritures de la base.
