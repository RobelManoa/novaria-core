# Preuve LOC-02 : premier démarrage réel de MongoDB sous Docker

Issue LOC-02 (#145). Critère : les 12 contrôles MongoDB de `db-check` sont `[OK]`, un document conforme est accepté et un document non conforme est refusé. Les sorties ci-dessous sont celles du 27/10/2026.

## Conditions

| Élément | Valeur |
|---|---|
| Poste | Windows 11 Pro, Docker Desktop (moteur 29.1.3), PowerShell |
| Image | `mongo:7` (mongosh 2.8.2) |
| Fichiers utilisés | ceux du dépôt, sans modification : `docker-compose.yml`, `db/mongo/init/01-collections-et-utilisateurs.js`, `.env` créé par `init-env` |
| Volumes | **neufs**, dans un projet Compose à part (`COMPOSE_PROJECT_NAME=novaria-loc02`) : c'est un vrai premier démarrage. Les volumes habituels `novaria-core_pgdata` et `novaria-core_mongodata` n'ont pas été touchés |
| Projet jetable | supprimé après la preuve : `docker compose -p novaria-loc02 down -v` |

Le script d'initialisation s'est exécuté sans erreur au premier essai : **aucune correction** de `db/mongo/init/01-collections-et-utilisateurs.js` n'a été nécessaire. Les deux messages `Failed to authenticate ... UserNotFound: svc_backend` du journal de MongoDB sont ceux de la sonde de santé, lancée avant la création des utilisateurs ; elle réussit ensuite (conteneur `Healthy`).

## 1. `db-up` puis `db-check`

```text
> py -3 scripts/dev/dev.py db-up
 Container novaria-loc02-postgres-1 Healthy
 Container novaria-loc02-mongo-1 Healthy
Application de 0001_dwh_dimensions.sql
Application de 0002_dwh_faits.sql
Application de 0003_alertes.sql
Application de 0004_donnees_de_reference.sql
Application de 0005_reseau_demo.sql
Migrations : 5 appliquée(s), 0 déjà présente(s).

> py -3 scripts/dev/dev.py db-check
  [OK] postgres administrateur : 4 schémas présents
  [OK] postgres administrateur : migrations appliquées
  [OK] postgres traitement lit l'entrepôt (dwh)
  [OK] postgres traitement ne lit PAS les alertes
  [OK] postgres alerte lit ses règles
  [OK] postgres alerte ne lit PAS l'entrepôt
  [OK] postgres lecture seule : lit l'entrepôt
  [OK] postgres lecture seule : n'écrit PAS
  [OK] postgres API métier n'accède PAS à l'entrepôt
  [OK] mongo    administrateur : 6 collections
  [OK] mongo    administrateur : index de durée de vie sur raw_events
  [OK] mongo    collecte lit raw_events
  [OK] mongo    collecte ne lit PAS audit_logs
  [OK] mongo    traitement lit raw_events
  [OK] mongo    traitement ne lit PAS model_runs
  [OK] mongo    réponse lit audit_logs
  [OK] mongo    réponse ne lit PAS raw_events
  [OK] mongo    backend lit usage_stats
  [OK] mongo    backend ne lit PAS raw_events
  [OK] mongo    ML lit model_runs
  [OK] mongo    ML ne lit PAS audit_logs
Toutes les vérifications passent.
```

12 lignes `mongo` sur 12 en `[OK]` (21 au total avec PostgreSQL).

## 2. Les deux insertions avec le compte `svc_collecte`

Commande rejouable : `py -3 scripts/dev/dev.py db-check-events` (Linux : `python3 ...` ou `make db-check-events`). Elle part de `contracts/events/examples/mesure-valide.json`, convertit `time` en date, ajoute `received_at` (posé par le service de collecte à l'écriture, absent de l'événement publié sur le bus), insère avec `svc_collecte`, puis supprime ses documents d'essai (identifiants terminés par `:db-check`).

```text
> py -3 scripts/dev/dev.py db-check-events
  [OK] mongo    collecte : mesure conforme acceptée
  [OK] mongo    collecte : mesure sans provenance refusée (validateur)
  [OK] mongo    raw_events : index de durée de vie de 14 jours
Toutes les vérifications passent.
```

Détail des deux insertions, rejouées à la main dans mongosh avec le même compte :

```text
# 1. mesure-valide.json (time et received_at en dates) : acceptée
{"acknowledged":true,"insertedId":"6ae0940d1fda100b9a44ba89"}

# 2. même document, `data.provenance` retiré : refusée
MongoServerError: Document failed validation
  operatorName: '$jsonSchema'
  propertyName: 'data'
  operatorName: 'required', specifiedAs: { required: [ 'provenance' ] }, missingProperties: [ 'provenance' ]
```

Après les deux essais, `raw_events` contient 1 document (le conforme) : le refusé n'a rien écrit.

Contrôles complémentaires, même compte, même session :

| Essai | Résultat |
|---|---|
| `time` laissé en texte (`"2026-10-20T08:00:10Z"`) au lieu d'une date | Refusé : `propertyName: 'time'`, `reason: 'type did not match'` : la conversion en date est bien exigée |
| Même `id` inséré deux fois | Refusé : `E11000 duplicate key ... index: uniq_event_id` (idempotence) |
| `svc_backend` insère dans `raw_events` | Refusé : `not authorized on novaria to execute command { insert: "raw_events" ... }` |

## 3. Index de durée de vie de `raw_events`

`db.raw_events.getIndexes()` (administrateur) :

```text
[
  { v: 2, key: { _id: 1 }, name: '_id_' },
  { v: 2, key: { id: 1 }, name: 'uniq_event_id', unique: true },
  { v: 2, key: { subject: 1, time: -1 }, name: 'subject_time' },
  { v: 2, key: { received_at: 1 }, name: 'ttl_received_at', expireAfterSeconds: 1209600 }
]
```

`expireAfterSeconds: 1209600` = 14 × 86 400 s = **14 jours**, porté par `received_at` (`RAW_EVENTS_TTL_SECONDS`). `db-check-events` compare cette valeur à la variable du conteneur.

## Limites

- Exécuté sous Windows. Le plan de démarrage ([demarrage-binome.md](../07-gestion/demarrage-binome.md)) prévoit LOC-02 sous Linux : la même commande reste à rejouer sur ce poste (`make db-check` puis `make db-check-events`) pour confirmer l'équivalence.
- La suppression effective d'un document par le moniteur de durée de vie (au bout de 14 jours, vérifié toutes les 60 s par MongoDB) n'est pas observée ici : seule la définition de l'index l'est.
- Sauvegarde et restauration MongoDB : hors périmètre, c'est LOC-03.
