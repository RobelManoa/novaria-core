# Novaria Core : consignes pour Claude

Ce fichier est lu au début de chaque session Claude Code ouverte dans ce dépôt. Il vaut pour les deux membres du binôme.

## 1. Première réponse de chaque session

Demander, en une phrase, **le système et le terminal** de la personne, sauf si elle l'a déjà dit :

| Personne | Système | Terminal | Lanceur |
|---|---|---|---|
| Manoa Robel | Linux (Ubuntu) | bash | `python3 scripts/dev/dev.py <commande>` (ou `make <commande>`) |
| Daddy Luciano | Windows | PowerShell | `py -3 scripts/dev/dev.py <commande>` |

Toute commande donnée dans une réponse ou dans un document existe **dans les deux variantes** dès qu'elle diffère (chemins, variables d'environnement, activation d'un environnement Python, `make`). `make` n'existe pas sous Windows.

## 2. Le projet en six lignes

- **Novaria Core** : plateforme de mobilité urbaine (détection de congestion, alertes usagers, recommandations de signalisation). Projet du bloc de compétences BC05 (Master 2 EADL, *Expert en Architectures et Développement Logiciels*, MCCI Business School), soutenance le 10/12/2026.
- Dépôt **public** : aucun secret, aucune donnée sous licence restrictive, aucun jeu réel redistribué.
- Architecture : microservices (collecte, traitement, alerte usager, réponse extérieure) + passerelle + simulateur, bus d'événements Kafka, PostgreSQL 16 (schémas `app`, `dwh`, `alertes`, `ops`), MongoDB 7.
- **Exécution locale d'abord** (consigne du professeur, ADR-023) : tout tourne avec Docker Compose sur le poste. **Aucune ressource AWS (Amazon Web Services) n'est créée.** Les documents AWS restent comme cible documentée.
- Ordre de l'IA (intelligence artificielle) : détection de congestion d'abord, prévision ensuite (ADR-015). Le label vient de la vérité terrain du simulateur (ADR-027). Seuils et alertes : ADR-028.
- Répartition : Manoa = analyse, données, IA, documentation ; Daddy = back-end, développement. Chaque issue a un responsable ; la relecture est croisée.

## 3. Où chercher avant de répondre

| Besoin | Fichier |
|---|---|
| Décisions | `docs/01-architecture/adr/README.md` (index), ADR-023 à ADR-028 pour la version locale |
| Tables, colonnes, codes de rejet | `docs/03-donnees/dictionnaire-de-donnees.md` |
| Contrats d'événements | `contracts/events/` et `contracts/README.md` |
| Bases locales | `docs/03-donnees/base-de-donnees-locale.md`, `db/` |
| Poste de travail, dépannage | `docs/08-exploitation/poste-de-travail.md` |
| Sauvegarde et restauration | `docs/08-exploitation/sauvegarde-restauration-locale.md` |
| Équivalents locaux des services AWS | ADR-025 |
| Ordre de travail du binôme | `docs/07-gestion/demarrage-binome.md` |
| Backlog | issues GitHub, identifiants `[ID]` (voir `scripts/github/`) |

## 4. Conventions

- Branche par issue : `feature/<ID>-titre-court` (`fix/...`, `docs/...`). Jamais de commit direct sur `main` (protégée : pull request, 1 approbation, fusion par squash).
- Commit : `type(portée): résumé` avec `feat`, `fix`, `docs`, `test`, `chore`, `ci`, `refactor`. Exemple : `feat(backend): ajoute l'authentification JWT`.
- Pull request : `Closes #n` dans la description ; CI (Continuous Integration, intégration continue) verte (backend, frontend, gitleaks, snyk, docker, sonarqube) ; relecture par l'autre membre.
- Fins de ligne LF (`.gitattributes`, `.editorconfig`). Fichiers écrits en UTF-8 par l'outil lui-même (option `--out`), jamais par la redirection `>` de PowerShell.
- Chemins avec `/` dans les fichiers du dépôt.
- Tout outil commun est en **Python (bibliothèque standard)**, pas en shell.
- Chaque usage significatif de l'IA est consigné dans `docs/ia/journal-usage-ia.md` : but, prompt, vérification.

## 5. Style des documents (français)

- Français correct, phrases courtes, forme affirmative.
- Une abréviation est **développée à côté de sa première occurrence** dans le document (exemple : SUMO (Simulation of Urban MObility)).
- Plus de schémas et de tableaux, moins de prose. Les diagrammes sont en Mermaid.
- Un document technique donne les commandes Linux et Windows en deux colonnes.
- Ne rien affirmer qui n'ait été vérifié : écrire « non vérifié » ou « à vérifier » quand c'est le cas.

## 6. Interdits (sans accord écrit des deux membres)

- Créer une ressource AWS, ou les variables GitHub `AWS_ROLE_ARN` / `AWS_REGION` (elles activeraient `deploy.yml` et `terraform.yml`).
- Modifier la protection de `main`, les paramètres du dépôt ou les contrôles de la CI ; désactiver ou contourner un contrôle (`--no-verify`, `continue-on-error`, suppression d'un test).
- Fusionner une pull request à la place du relecteur.
- Écrire un secret (mot de passe, jeton, clé) dans un fichier, une capture, un message de commit ou le chat ; les secrets viennent de `.env` (ignoré par Git).
- Commiter `.env`, `backups/`, `var/`, un jeu de données de plus de 1 Mo ou un jeu réel.
- Présenter une donnée simulée comme réelle.
- Lancer une commande destructive (`db-reset`, `restore`, `docker volume rm`, `git push --force`) sans que la personne l'ait demandée dans le même message.

## 7. Commandes de référence

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Vérifier le poste | `python3 scripts/dev/dev.py check-tools` | `py -3 scripts/dev/dev.py check-tools` |
| Créer `.env` (mots de passe aléatoires) | `python3 scripts/dev/dev.py init-env` | `py -3 scripts/dev/dev.py init-env` |
| Démarrer les bases | `python3 scripts/dev/dev.py db-up` | `py -3 scripts/dev/dev.py db-up` |
| Vérifier rôles, droits, index | `python3 scripts/dev/dev.py db-check` | `py -3 scripts/dev/dev.py db-check` |
| Sauvegarder | `python3 scripts/dev/dev.py backup` | `py -3 scripts/dev/dev.py backup` |
| Contrôler la sauvegarde | `python3 scripts/dev/dev.py restore-check` | `py -3 scripts/dev/dev.py restore-check` |
| Tests des contrats | `python3 -m unittest discover -s contracts/tests` | `py -3 -m unittest discover -s contracts/tests` |
| Tests de `dev.py` | `python3 -m unittest discover -s scripts/dev` | `py -3 -m unittest discover -s scripts/dev` |
| Tests du backlog | `python3 -m unittest discover -s scripts/github -p "test_*.py"` | `py -3 -m unittest discover -s scripts/github -p "test_*.py"` |
| Essai de mise à jour du backlog | `python3 scripts/github/sync_backlog.py --dry-run` | `py -3 scripts/github/sync_backlog.py --dry-run` |

## 8. Travailler sur une issue

1. Lire l'issue (tâches, critère d'acceptation, preuve attendue, dépendances) et les documents du tableau du point 3 qui la concernent.
2. Annoncer le plan en quelques lignes avant de modifier des fichiers.
3. Créer la branche `feature/<ID>-titre`, faire de petits commits.
4. Exécuter les tests et les contrôles du poste ; coller la sortie utile (sans secret) dans l'issue comme preuve.
5. Ouvrir la pull request avec `Closes #n`, demander la relecture à l'autre membre.
6. Consigner l'usage de l'IA dans `docs/ia/journal-usage-ia.md`.

Le gabarit de prompt est dans `docs/ia/prompt-modele-issue.md`.
