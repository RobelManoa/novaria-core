# Dépendances Python verrouillées

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsable : Manoa Robel, relecture par Daddy Luciano
Dernière mise à jour : 27/10/2026
Origine : analyse SonarQube Cloud de la pull request MS-06 (règles Docker `S8541` et `S8544`)

Chaque image de service installe **exactement** les paquets que l'équipe a relus, vérifiés par empreinte, et sans exécuter de script d'installation. Ce document dit comment, pourquoi, et comment ajouter ou mettre à jour une dépendance.

## 1. Pourquoi

| Règle Sonar | Ce qu'elle reproche | Réponse |
|---|---|---|
| `docker:S8541` : « Python package manager scripts should not be executed during installation » | `pip install` sans `--only-binary :all:` peut compiler un paquet source et lancer son script d'installation | `--only-binary :all:` : seuls des paquets binaires (roues) sont installés |
| `docker:S8544` : « Python dependencies should be locked to verified versions » | Des versions « au moins » (`>=0.115`) donnent une image différente à chaque construction, et rien ne prouve que le paquet téléchargé est celui qu'on attend | Versions exactes et empreintes SHA-256 (`--require-hashes`) : un paquet modifié, ou une autre version, est refusé |

Ces deux règles sont classées vulnérabilités : une seule suffit à faire échouer la porte de qualité de SonarQube (note de sécurité). Au-delà de Sonar, c'est la protection de la chaîne d'approvisionnement du projet : une image reconstruite demain contient les mêmes paquets qu'aujourd'hui.

## 2. Comment c'est fait

| Fichier (dans chaque dossier de `services/`) | Rôle | Qui l'écrit |
|---|---|---|
| `requirements.in` | Dépendances **de l'application**, en intervalles (`fastapi>=0.115,<1.0`) | Une personne |
| `requirements-dev.in` | Idem, plus les outils de test et de lint (`-r requirements.in` en tête) | Une personne |
| `requirements.txt` | **Verrou** de l'application : chaque paquet, y compris les dépendances indirectes, en version exacte avec ses empreintes | `dev.py lock-deps` |
| `requirements-dev.txt` | Verrou du développement et de la CI | `dev.py lock-deps` |

| Où | Utilisation |
|---|---|
| `Dockerfile` | `pip install --require-hashes --only-binary :all: -r requirements.txt` |
| CI, job `service` | `pip install -r requirements-dev.txt` (pip active seul le contrôle des empreintes) |
| CI, job `snyk` | analyse `requirements.txt` : des versions exactes donnent un résultat exact |
| Poste | `pip install -r requirements-dev.txt` dans l'environnement du service |

Le verrou est **universel** : il couvre Linux, Windows et macOS, et Python 3.12 et suivants (par exemple `colorama` n'est demandé que sous Windows, et l'image Python 3.15 y trouve ses roues). Il est calculé par `uv pip compile --universal --generate-hashes` dans un conteneur `python:3.12-slim`, avec la version de l'outil fixée (`UV_VERSION` dans `scripts/dev/dev.py`) : deux postes produisent le même fichier.

## 3. Ajouter ou mettre à jour une dépendance

| Étape | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| 1. Modifier le `.in` du service (une borne de version, comme les lignes existantes) | éditer `services/<nom>/requirements.in` (ou `requirements-dev.in` pour un outil de test) | idem |
| 2. Recalculer les verrous (Docker et réseau nécessaires) | `python3 scripts/dev/dev.py lock-deps <nom>` (ou sans nom pour tous les services ; `make lock-deps`) | `py -3 scripts/dev/dev.py lock-deps <nom>` |
| 3. Relire le diff des `.txt`, lancer lint et tests | `cd services/<nom> && ruff check . && ruff format --check . && pytest` | `cd services/<nom>; ruff check .; ruff format --check .; pytest` |
| 4. Reconstruire l'image | `docker build -t novaria-<nom> services/<nom>` | idem |
| 5. Commiter les `.in` et les `.txt` **ensemble** | | |

Une dépendance sans roue pour la version de Python de l'image fait échouer l'étape 4 (`No matching distribution found`) : c'est voulu. Chercher alors une version qui en a une, ou ne pas ajouter l'option qui l'apporte. Exemple vécu : `uvicorn[standard]` apportait `pyyaml`, sans roue pour Python 3.15 à la date de ce document ; les services utilisent donc `uvicorn` seul.

## 4. Limites et points à vérifier

| Point | État |
|---|---|
| Dependabot | La configuration (`.github/dependabot.yml`, écosystème `pip`, `/services/*`) n'a pas changé. Il lit les `.in` et les `.txt` compilés ; s'il propose une mise à jour qui ne régénère pas le verrou, relancer `dev.py lock-deps` sur la branche. **Non vérifié** : le premier cycle mensuel le dira |
| Copie dans chaque service | Les cinq services (gabarit compris) ont aujourd'hui des verrous identiques, calculés séparément. Un service qui ajoute une dépendance a un verrou différent : c'est normal |
| Réseau | `lock-deps` télécharge l'outil et interroge l'index des paquets : il ne fonctionne pas hors ligne |
| Simulateur | `simulator/` n'a aucun paquet (bibliothèque standard) : rien à verrouiller |
| Frontend | Les dépendances npm sont déjà verrouillées par `package-lock.json` (`npm ci`) |
