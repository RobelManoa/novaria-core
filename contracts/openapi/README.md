# Contrats OpenAPI par service

Un contrat par service ([ADR-008](../../docs/01-architecture/adr/ADR-008-microservices.md), règle 4), qui remplace le contrat unique de BE-01. Statut : **brouillon** ; la validation du professeur (GES-06) et la relecture croisée sont attendues. Les passages marqués « Proposition » sont des choix du binôme à confirmer.

| Fichier | Service | Rôle | Opérations |
|---|---|---|---|
| `api-metier.openapi.yaml` | API métier (service à créer depuis le gabarit, BE-02 et BE-03) | Santé, authentification, comptes | 7 |
| `traitement.openapi.yaml` | Traitement | Référentiel, indicateurs, prévisions | 8 |
| `alerte.openapi.yaml` | Alerte usager | Alertes, règles, flux SSE (Server-Sent Events) | 8 |
| `reponse.openapi.yaml` | Réponse extérieure | État des feux, commande manuelle | 5 |
| `collecte.openapi.yaml` | Collecte | Dépôt des mesures par le simulateur (réseau interne) | 2 |
| `common.yaml` | (aucun) | Composants partagés par au moins deux services : erreur, pagination, provenance, paramètres, réponses d'erreur, sonde | — |

Chaque service décrit sa propre sonde `GET /api/v1/health` (même contenu partout) : chacun en a besoin pour la sonde de santé de Docker. Les 24 autres opérations de BE-01 appartiennent chacune à un seul service ; `POST /api/v1/measurements` est nouveau.

## Routage derrière la passerelle

Tous les chemins commencent par `/api/v1`, comme dans BE-01 : le client du tableau de bord n'a pas à connaître les services. La passerelle (MS-13) route par préfixe.

| Préfixe | Service |
|---|---|
| `/api/v1/auth`, `/api/v1/users` | API métier |
| `/api/v1/intersections`, `/api/v1/road-segments`, `/api/v1/indicators`, `/api/v1/forecasts` | Traitement |
| `/api/v1/alerts`, `/api/v1/alert-rules`, `/api/v1/events` | Alerte usager |
| `/api/v1/signals` | Réponse extérieure |
| `/api/v1/health` | API métier (la sonde des autres services n'est pas exposée) |
| `/api/v1/measurements` | **Non exposé** : réseau interne, simulateur vers collecte |

## Conventions communes

| Sujet | Règle |
|---|---|
| Version | `/api/v1` dans chaque chemin |
| Format | JSON, UTF-8. Noms techniques en anglais `snake_case`, descriptions en français |
| Dates | ISO 8601 en UTC, fuseau explicite : `2026-10-20T08:00:10Z`. Aucune heure locale |
| Unités | Vitesse en km/h, débit en véhicules par minute, taux d'occupation de 0 à 1, longueurs en mètres |
| Valeur absente | `null`, jamais `0` ni `-1`. Une vitesse n'existe que si un véhicule est passé |
| Provenance | Chaque indicateur, alerte et prévision porte `provenance`. Une donnée simulée n'est jamais présentée comme réelle |
| Identifiants | `INT_01` (carrefour), `ROAD_001` (tronçon), UUID (alerte, épisode, commande) |
| Corrélation | L'en-tête `X-Correlation-ID` est lu s'il est fourni, généré sinon, et renvoyé à chaque réponse |
| Champs d'événement | Les schémas `Indicator`, `Alert` et les énumérations reprennent `contracts/events/` ; un test le vérifie |

Définition de chaque champ : [dictionnaire de données](../../docs/03-donnees/dictionnaire-de-donnees.md) ; valeurs de `congestion_state` : ADR-028.

### Authentification

Jeton porteur JWT (JSON Web Token) obtenu par `POST /api/v1/auth/login` (API métier) et envoyé dans `Authorization: Bearer <jeton>`. La passerelle le contrôle ; les services derrière elle reçoivent des requêtes déjà authentifiées.

| Élément | Valeur |
|---|---|
| Durée de vie | `expires_in` secondes (valeur de départ : 1800). Pas de jeton de renouvellement en v1 : se reconnecter |
| Revendications | `sub` (identifiant utilisateur), `role`, `iat`, `exp` |
| Signature | Secret `JWT_SECRET` lu dans l'environnement. Algorithme : HS256 (Proposition) |
| Sans jeton valide | `401` |
| Jeton valide, rôle insuffisant | `403` |
| Routes publiques | `GET /api/v1/health` et `POST /api/v1/auth/login` ; `POST /api/v1/measurements` (interne, Proposition) |

### Rôles

Proposition à valider : trois rôles hiérarchiques. Un rôle inclut les droits du précédent.

| Rôle | Droits |
|---|---|
| `viewer` | Lire indicateurs, alertes, prévisions, feux, référentiel. Compte du Robot RPA (lecture seule) |
| `operator` | + acquitter et résoudre une alerte, envoyer une commande manuelle aux feux |
| `admin` | + gérer les utilisateurs et les règles d'alerte |

### Erreurs et pagination

| Sujet | Règle |
|---|---|
| Erreurs | Toute erreur a le même corps, `application/problem+json` (RFC 9457), schéma `Problem` de `common.yaml`. Le champ `code` est stable et lisible par une machine ; `detail` est destiné à une personne |
| Listes | `{ items, next_cursor }`. Le curseur est opaque : le client le renvoie tel quel dans `cursor`. `next_cursor` vaut `null` sur la dernière page. `limit` : 1 à 500, défaut 100 |

### Versionnement

| Changement | Conséquence |
|---|---|
| Ajouter un champ de réponse, un paramètre facultatif, un point d'accès, une valeur d'énumération de réponse | Compatible : même version `/api/v1`. Les clients ignorent les champs inconnus |
| Retirer ou renommer un champ, resserrer une règle, changer une unité, ajouter un paramètre obligatoire | Rupture : nouvelle version `/api/v2`. Les deux coexistent pendant la transition |
| Retrait annoncé | En-têtes `Deprecation` et `Sunset` (RFC 9745 et RFC 8594) sur les réponses concernées |

`info.version` suit la forme `majeure.mineure.correctif` du contrat. La version du produit déployé est donnée par `GET /api/v1/health`. Les règles de versionnement des **événements** sont dans le [README des contrats](../README.md).

## Points d'accès par service

| Service | Étiquette | Point d'accès | Rôle minimal | Issue d'implémentation |
|---|---|---|---|---|
| tous | Santé | `GET /health` | public | existe (API métier) |
| API métier | Authentification | `POST /auth/login` (public), `GET /auth/me` | `viewer` | BE-03 |
| API métier | Utilisateurs | `GET`, `POST /users` ; `GET`, `PATCH /users/{user_id}` | `admin` | BE-02, BE-03 |
| Traitement | Référentiel | `GET /intersections`, `/intersections/{id}`, `/road-segments` | `viewer` | MS-10 |
| Traitement | Indicateurs | `GET /indicators`, `/indicators/latest`, `/indicators/{id}` | `viewer` | BE-04, MS-10 |
| Traitement | Prévisions | `GET /forecasts` | `viewer` | IA-06 |
| Alerte usager | Alertes | `GET /alerts`, `/alerts/{id}` ; `POST /alerts/{id}/acknowledge`, `/resolve` ; `GET /alert-rules` ; `PATCH /alert-rules/{id}` | `viewer`, `operator`, `admin` | MS-11 |
| Alerte usager | Flux | `GET /events/stream` (SSE) | `viewer` | MS-11 |
| Réponse extérieure | Feux | `GET /signals`, `/signals/{id}`, `/signals/{id}/commands` ; `POST /signals/{id}/commands` | `viewer`, `operator` | MS-12 |
| Collecte | Mesures | `POST /measurements` | interne | MS-08 |

## Vérifier les contrats

| Étape | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Installer PyYAML (une fois) | `python3 -m pip install pyyaml` | `py -3 -m pip install pyyaml` |
| Tester les contrats | `python3 -m unittest discover -s scripts/dev -p "test_openapi.py"` | `py -3 -m unittest discover -s scripts/dev -p "test_openapi.py"` |
| Tester la sonde d'un service contre son contrat | `cd services/traitement && python -m pytest tests/contract` | `cd services/traitement; python -m pytest tests/contract` |

Le test charge chaque fichier, résout toutes les références (locales, vers `common.yaml`, vers les schémas d'événements), contrôle les identifiants d'opération, la sécurité, le format d'erreur unique et la concordance avec `contracts/events/`. Il vérifie aussi le découpage : les 25 opérations de BE-01 sont toutes présentes, chaque chemin appartient à un seul service, un composant de `common.yaml` sert au moins deux services, aucun composant n'est orphelin ni défini deux fois. Il ne remplace pas un validateur OpenAPI complet : non exécuté ici, à lancer par exemple avec `npx @redocly/cli lint contracts/openapi/traitement.openapi.yaml`.

## Points ouverts

| N° | Point | Position dans le brouillon | Qui |
|---|---|---|---|
| 1 | Rôles | Trois rôles hiérarchiques `viewer`, `operator`, `admin` ; aucun document ne les définissait | Daddy et Manoa |
| 2 | Signature du jeton | HS256 avec `JWT_SECRET` ; pas de jeton de renouvellement | Daddy |
| 3 | Qui valide le jeton | L'API métier l'émet ; la passerelle ou le service le contrôle (README des diagrammes C4, point 2) | Daddy |
| 4 | Diffusion en direct | SSE plutôt que WebSocket. `EventSource` ne pose pas d'en-tête `Authorization` : fetch en flux ou jeton à usage unique | Daddy |
| 5 | Qui sert le flux SSE | Le service d'alerte, qui lit `alerts.events` et `signal.status`. Si la passerelle le sert, `topics.json` et `alerte.openapi.yaml` changent ensemble | Daddy |
| 6 | Feux | Les schémas `SignalState` et `SignalCommand` doivent rester alignés sur le contrat d'événement `signal.status` (durées en secondes, phases `P1`…) ; règles de sécurité des feux à écrire (EXG-REP-02, MS-12) | Daddy et Manoa |
| 7 | Prévisions | Servies par le service de traitement, qui lit les prévisions du module d'apprentissage ; à confirmer avec IA-06 | Manoa |
| 8 | Page « Rapports » du front | Aucun point d'accès : le besoin n'est pas défini | Manoa |
| 9 | Indicateurs agrégés (KPI) | Aucun point d'accès tant que les définitions de DAT-07 ne sont pas figées | Manoa |
| 10 | Format d'erreur | FastAPI renvoie `{"detail": ...}` par défaut : un gestionnaire d'exceptions doit produire `application/problem+json` (BE-06) | Daddy |
| 11 | Authentification de la collecte | Le dépôt des mesures n'est pas protégé en v1 (réseau interne) ; authentification de service à décider (CLD-18) | Daddy |
| 12 | Client typé du tableau de bord (FE-02) | Un client par service, ou une génération à partir des cinq contrats avec les références de `common.yaml` ; non tranché | Manoa |

## Client TypeScript du tableau de bord

Le front-end génère ses types depuis ces fichiers (`npm run api:generate` dans `frontend/`) et un test échoue si les types ne suivent pas un changement de contrat. Pour modifier un contrat : changer le YAML, lancer `npm run api:generate`, puis corriger les erreurs de compilation signalées. Voir [frontend/README.md](../../frontend/README.md#client-dapi-typé).
