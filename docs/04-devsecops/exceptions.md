# Exceptions de sécurité

Toute exception Snyk doit avoir une raison, une date d'expiration et être revue avant cette date.

| Identifiant Snyk | Composant | Image | Raison | Expiration |
|---|---|---|---|---|
| SNYK-DEBIAN13-ZLIB-19520500 | zlib1g (Out-of-bounds Write) | backend (python:3.12-slim, Debian 13) | Aucun correctif publié par Debian à la date du 2026-10-17 | 2026-11-15 |
| SNYK-DEBIAN13-ATTR-17678182 | libattr1 (Link Following) | backend (python:3.12-slim, Debian 13) | Aucun correctif publié par Debian à la date du 2026-10-17 | 2026-11-15 |
| SNYK-DEBIAN13-ACL-17677866 | libacl1 (Link Following) | backend (python:3.12-slim, Debian 13) | Aucun correctif publié par Debian à la date du 2026-10-17 | 2026-11-15 |

## Revue

Avant l'expiration, reconstruire l'image backend (la ligne `apt-get upgrade` du Dockerfile récupère les correctifs publiés) et relancer l'analyse. Si les vulnérabilités sont corrigées, supprimer l'exception. Sinon, la renouveler avec une nouvelle date.
