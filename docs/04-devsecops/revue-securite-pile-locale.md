# Revue de sécurité de la pile locale et de la dépendance à AWS

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 19/11/2026
Statut : à valider par les deux membres (relecture de la pull request)

Portée : tout ce qui tourne sur le poste (Docker Compose, services, bases, bus) et tout ce qui touche AWS. Le projet s'exécute **en local** ([ADR-023](../01-architecture/adr/ADR-023-execution-locale-d-abord.md)) : aucune ressource AWS n'est créée. Cette revue dit ce qui a été **vérifié**, ce qui a été **corrigé**, et ce qui **reste**.

Abréviations : **CVE** (Common Vulnerabilities and Exposures, identifiant public d'une faille), **CI** (Continuous Integration, intégration continue), **OIDC** (OpenID Connect, authentification sans clé longue durée), **ACL** (Access Control List, liste de droits), **TLS** (Transport Layer Security, chiffrement des échanges).

## 1. Vérifié le 19/11/2026

| Sujet | Comment | Résultat |
|---|---|---|
| Ports exposés | `docker compose config` : tous les ports publiés | **Dix ports publiés, tous sur `127.0.0.1`** : rien n'est joignable depuis le réseau |
| Droits des conteneurs | `docker compose config` et `docker ps` | Aucun `privileged`, aucun `network_mode: host`, aucune socket Docker montée (test `test_compose.py`) ; les images applicatives tournent sans droits (`USER appuser` ou `USER 101`) |
| Secrets du dépôt | `gitleaks detect` sur l'historique, puis sur l'arbre de travail | Historique : seuls les deux faux positifs documentés ([exceptions](exceptions.md), section 11). Arbre : les valeurs de `.env` (ignoré par Git) et deux anciens fichiers de `var/` (ignoré) ; **rien de suivi** |
| `.env` | `git check-ignore`, longueur des valeurs | Ignoré par Git ; **12 secrets générés au hasard, aucun de moins de 20 caractères**, aucune valeur par défaut |
| Dépendances Python | `pip-audit` sur chaque verrou (`services/*`, `ml`, `data/etl`) | Une faille : `opentelemetry-api` 1.45.1 (CVE-2026-126360) dans `collecte` et `traitement`. **Corrigée** (section 2) |
| Dépendances du front-end | `npm audit --omit=dev` | **0 faille** en production ; 7 de gravité moyenne dans les outils de construction (développement seulement), non traitées |
| Code AWS dans l'exécution | recherche de `boto3`, de SDK, de variables `AWS_*` hors documents et infrastructure | **Aucun** ; un test (`test_absence_sdk_aws.py`) l'impose pour `ml/` |
| Workflows AWS | `deploy.yml`, `terraform.yml` | Inactifs : ils exigent la variable `AWS_ROLE_ARN`, qui n'existe pas |

## 2. Corrigé

| Défaut | Correctif | Preuve |
|---|---|---|
| Un faille connue dans `opentelemetry-api` (collecte, traitement) | Relevé en **1.45.2** dans les quatre verrous concernés, sans autre changement de version | `pip-audit` |
| Les services applicatifs gardaient les capacités Linux par défaut | `cap_drop: [ALL]` et `no-new-privileges` sur les **dix** services applicatifs (ancre `x-durcissement` de `docker-compose.yml`) ; les bases et Kafka sont exclus (leurs images démarrent avec des droits qu'elles abandonnent) | Test `test_compose.py` ; la pile recréée sert le **flux complet** (neuf cas rejoués sur la pile durcie : nominal, message invalide, service arrêté) |
| `scripts/github/secrets.sh aws` enregistrait les variables qui activent `deploy.yml` et `terraform.yml`, donc des ressources AWS payantes | Il **refuse** sans `NOVARIA_AWS_AUTORISE=accord-ecrit-des-deux-membres` et n'appelle pas `gh` | `test_secrets_aws.py` (un faux `gh` détecte tout appel) |
| Les verrous de développement de quatre services n'incluaient pas `colorama` ni `tzdata` pour Windows : l'installation avec empreintes aurait échoué sur le poste de Daddy | Verrous régénérés avec la même commande (`uv pip compile --universal`), versions inchangées | `test_dependances.py` : les sept échecs anciens passent |
| Pas de contrôle du code Terraform sans compte | Protections des ressources persistantes, plan rejoué sur un émulateur local | [Ressources persistantes](../05-cloud-aws/ressources-persistantes.md) |

## 3. Ce qui reste (non corrigé)

| Point | Pourquoi | Piste |
|---|---|---|
| Kafka sans authentification ni ACL, en `PLAINTEXT` | Local, port lié à `127.0.0.1` ; défaut connu du projet | SASL et ACL par service, à décider avant toute exposition réseau |
| Dépôt des mesures sur la collecte **sans authentification** | Choix de départ (capteurs simulés) | Jeton par capteur |
| Pas de TLS entre les services | Tout est sur le réseau interne de Docker, sur le poste | TLS à la passerelle si le projet quitte `localhost` |
| Jeton JWT à clé symétrique (HS256) partagée entre services | Simple, secret généré au hasard | Clés asymétriques, rotation |
| `.env` en `777` sur le disque monté | Le système de fichiers Windows monté sous Linux n'a pas de droits Unix ; `chmod 600` est sans effet | Garder le dépôt sur un disque Linux |
| Snyk (code, dépendances, conteneurs, IaC) non lancé sur ce poste | Pas de jeton | Le job `snyk` de la CI le joue sur chaque pull request |
| Images de base non analysées ici | Même raison | Job `docker` de la CI |
| Sept failles moyennes dans les outils de construction du front-end | Développement seulement, pas dans les images | `npm audit fix` après relecture |
| Tout est vérifié sous Linux | Le poste de Daddy est sous Windows | Rejouer `dev.py check-tools` et les tests sous Windows |

## 4. Rejouer

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Ports et durcissement | `docker compose config --format json` puis lire `ports`, `cap_drop`, `security_opt` | idem avec `docker compose config --format json` |
| Secrets (historique et arbre) | `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest detect --source /repo --redact` (ajouter `--no-git` pour l'arbre) | `docker run --rm -v "${PWD}:/repo" zricethezav/gitleaks:latest detect --source /repo --redact` |
| Failles des dépendances Python | `pip install pip-audit` puis `pip-audit -r services/collecte/requirements.txt --no-deps --disable-pip` | idem avec `py -3 -m pip_audit …` |
| Failles du front-end | `cd frontend && npm audit --omit=dev` | idem |
| Tests de ce document | `python3 -m unittest discover -s scripts/dev -p "test_compose.py"` et `-p "test_dependances.py"`, puis `python3 -m unittest discover -s scripts/github -p "test_secrets_aws.py"` | idem avec `py -3` |
