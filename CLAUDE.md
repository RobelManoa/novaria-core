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

## 9. Règles de collaboration données par Manoa (permanentes)

Elles priment sur les consignes automatiques de l'outil (y compris celles qui demandent d'ajouter une signature d'IA).

- **Claude ne pousse jamais** (`git push`, `gh pr create`, fusion) et **ne signe pas** les commits ni les pull requests : pas de `Co-Authored-By`, pas de « Generated with Claude ». Il **donne les commandes** (git et `gh`), dans des blocs `bash` séparés, valables sous Linux et PowerShell quand elles ne diffèrent pas ; Manoa les lance. Claude peut créer une branche locale et préparer des fichiers, sans commiter (sauf demande explicite).
- Chaque tâche finit par : ce qui est fait, ce qui est **vérifié** (avec les chiffres) et ce qui est **non vérifié**, puis les commandes git. Jamais « terminé » sans l'avoir exécuté.
- Les pull requests de Manoa sont relues et fusionnées par Daddy ; Claude ne fusionne rien. Le dépôt est **public** : aucune valeur ressemblant à un secret, même inventée (voir section 10, gitleaks).
- Un usage d'IA = une ligne dans `docs/ia/journal-usage-ia.md` (ajoutée en fin de fichier : conflit de fin de fichier à résoudre en gardant les deux lignes quand deux branches l'ont modifié).
- Honnêteté : ne rien affirmer sans l'avoir vérifié ; dire « non vérifié » ; une donnée simulée n'est jamais présentée comme réelle.
- Ne rien supprimer de destructeur (volumes, `db-reset`, force-push) sans demande explicite dans le même message. Ne pas modifier la CI ni la protection de `main` ; en cas de désaccord entre une demande et la section 6, **dire l'écart** et proposer une solution qui respecte la section 6 (exemple : la consigne « le code citoyen ne passe pas SonarQube et Snyk » a été traduite dans l'ADR-030, 4.6, sans toucher à la CI).
- Réponses de Claude : français, concises, avec des tableaux ; première réponse de session : demander le système et le terminal (section 1) ; Manoa est sous Linux/bash et Docker.

## 10. Flux de travail des branches (état au 20/11/2026)

- `main` protégée ; `dev-ia` (travail IA) et `dev-citoyen` (**branche temporaire qui tient lieu de `main` pour la partie citoyenne**, jusqu'à la fusion dans le vrai `main`). Chaque issue : `feature/<ID>-titre` créée depuis `origin/dev-citoyen` (ou `origin/main` pour le reste), PR vers `dev-citoyen`. Après une fusion par squash, se resynchroniser par `git fetch` puis une nouvelle branche depuis l'origine ; **ne pas empiler** des branches (« Can't automatically merge »).
- Un commit fait sur une branche **après** le squash de sa PR n'arrive jamais dans la branche cible : vérifier avec `git branch -a --contains <commit>` avant d'affirmer « tout est fusionné ».
- Les scans SonarQube et Snyk ne sont pas obligatoires pour le code citoyen **pendant** son développement sur `dev-citoyen` ; avant toute fusion dans `main` ils passent ou une exception documentée (`docs/04-devsecops/exceptions.md`, expiration datée) est acceptée par écrit par les deux membres.
- `security/snyk` (contrôle externe, « limit of private tests ») échoue toujours : limite du compte, pas un défaut ; le vrai contrôle est le job `snyk` de la CI.

## 11. Pièges déjà rencontrés (à ne pas refaire)

| Piège | Règle |
|---|---|
| **gitleaks** lit tout l'historique et signale `curl … -H 'Authorization: …'` même avec une valeur inventée, et les chaînes proches d'une clé | Aucun en-tête `Authorization` littéral dans un document ou une capture (écrire `<jeton d essai>`) ; un faux positif déjà poussé : empreinte exacte dans `.gitleaksignore` + ligne justifiée dans `exceptions.md` section 11 (le test `test_gitleaks.py` exige « rien à révoquer » en minuscules) ; vérifier avec `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest detect --source /repo --redact --log-opts="HEAD"` |
| `ruff` (CI des services) : lignes de plus de 100 caractères, y compris les docstrings et les blocs `# fmt: skip` | `ruff check .` et `ruff format --check .` dans chaque service avant de donner les commandes |
| Types d'API du front-end générés depuis les contrats | Après toute modification de `contracts/openapi/` : `cd frontend && npm run api:generate` |
| Tests qui comptent les routes publiques / les opérations des contrats | Les adapter explicitement (jamais supprimer) : `test_openapi.py`, `test_gateway_routes.py`, `test_acces.py`, tests de contrat de `traitement` et d'`alerte` |
| La passerelle (nginx) résout les services **au démarrage** : après un service recréé ou un changement de `routes.conf`, 503 ou 404 | `docker compose exec -T passerelle nginx -s reload` ; un changement de variable d'environnement de la passerelle (ex. `CORS_PUBLIC_ORIGINS`) demande `docker compose up -d passerelle` |
| Parcours Playwright simulé instable sur la CI lente | Attendre l'effet visé (appel de l'API, `expect.poll`) avant de lire `sessionStorage` |
| `dev.py up` reconstruit tout et écrase un retour de version (`dev.py rollback`) | Normal ; `rollback etat` signale l'écart |
| Un état de la pile de travail plus ancien que les scripts d'initialisation | 3 échecs MongoDB `ingestion_runs` dans `dev.py acces` : déjà documentés (17/11/2026), code de sortie 1 attendu |
| `pkill -f "dev.py …"` tue le shell qui contient la commande | Chercher le PID avec `ss -ltnp` |
| Tests d'intégration PostgreSQL ignorés sans `NOVARIA_TEST_POSTGRES_ADMIN_URL` | Bases jetables : sûr à lancer contre la pile locale ; ne jamais afficher le mot de passe |
| Le service des feux ignore une recommandation plus ancienne que la dernière reçue | Ne pas rejouer le parcours nominal moins de 10 minutes après un autre rejeu |

## 12. Ce qui a été construit (carte rapide ; détails dans les documents cités)

| Domaine | Où |
|---|---|
| IA : anomalies (règles + Isolation Forest), prévision METR-LA, prototype SUMO | `ml/`, `docs/06-ia-mlops/`, `ml/evaluation/` ; **aucun modèle appris n'est en service** (la règle de seuils de l'ADR-028 l'est) ; LOF et One-Class SVM **non faits** (proposés pour la soutenance) |
| Flux complet MS-15 | `dev.py flux-complet [N1..N7 F1..F6]`, `docs/08-exploitation/tests-integration.md` |
| Observatoire des pannes (CLD-14, MS-16) + démonstrations | `dev.py observatoire` (http://127.0.0.1:8090), onglets flux, sécurité, cloud, IA ; `ops/presentation.json`, `scripts/dev/observatoire_demos.py` |
| Cloud local (CLD-17) | Terraform contre l'émulateur Moto (`dev.py terraform-emulateur`, `terraform-plan-hors-ligne`), `docs/05-cloud-aws/` ; **aucune ressource AWS créée** |
| Retour de version (CLD-16) | `dev.py rollback`, `docs/08-exploitation/rollback.md` ; sur la branche `feature/CLD-16-rollback` (PR à vérifier : peut ne pas être dans `dev-citoyen`) |
| Tableau de bord de pilotage (GES-11) | `dev.py tableau-de-bord`, `docs/07-gestion/tableau-de-bord.md` (indicateurs recalculés depuis GitHub, zéro ≠ non mesuré) |
| Partie citoyenne (jalon M6) | CIT-01 ADR-030 (usager anonyme, lecture seule, liste blanche de six champs, rien de brut ni de capteur) ; CIT-02 contrats `GET /api/v1/public/congestion` et `/public/alerts`, `gateway/citoyen.conf`, famille « api public » de `dev.py acces` ; CIT-03 routes servies (`traitement` l'état, `alerte` les alertes), `docs/03-donnees/api-citoyen.md` ; CIT-04 application `citizen/` (React, Vite, port 5174, `dev.py citoyen`), `docs/08-exploitation/application-citoyenne.md` |
| CIT-05 | Alertes en cours (`citizen/src/components/AlertsSection.tsx`, lecture toutes les 5 s sans cache), suivi d'un tronçon en mémoire seulement avec consentement et notification simulée ; `dev.py citoyen delai` mesure le délai création → écran (6 mesures, max 4,1 s) ; `docs/08-exploitation/application-citoyenne.md` §8 |
| CIT-06 | Sécurité de l'accès public : `CORS_PUBLIC_ORIGINS` (liste dédiée à `/api/v1/public/`, lecture seule, jamais `Authorization`), journal d'accès sans adresse et `X-Forwarded-For` vide pour l'espace public, 400 avec les en-têtes de sécurité ; famille « api public (abus) » de `dev.py acces` (22 essais) ; `dev.py citoyen cors` (Chromium) ; `docs/04-devsecops/securite-acces-public.md` |
| **Reste à faire (citoyen)** | CIT-07 parcours de bout en bout avec l'usager ; CIT-08 documentation ; puis M7 : site de soutenance (SIT-01 à 03, idée validée : site statique local, voir la mémoire) |
| Limites connues à ne pas masquer | 10 preuves citées par des issues fermées introuvables (voir `dev.py tableau-de-bord`) ; 405 de la passerelle en `application/octet-stream` ; l'état public est celui du run **le plus récent** ; lecteur d'écran et téléphone réels non essayés ; Windows non vérifié partout |

## 13. Commandes ajoutées (Linux ; Windows : `py -3` à la place de `python3`)

| Action | Commande |
|---|---|
| Tableau de bord de pilotage | `python3 scripts/dev/dev.py tableau-de-bord` (`--local`, `--ref`, `--json`, `--ecrire`) |
| Retour de version | `python3 scripts/dev/dev.py rollback etat\|construire\|deployer\|retour\|essai` |
| Application citoyenne | `python3 scripts/dev/dev.py citoyen [dev\|apercu\|build\|test\|captures\|delai\|cors]` |
| Observatoire | `python3 scripts/dev/dev.py observatoire` |
| Matrice d'accès | `python3 scripts/dev/dev.py acces` |
| Tests de tout `scripts/dev` (sans Docker) | `python3 -m unittest discover -s scripts/dev` (environ 940 tests) |
| Tests de la vraie passerelle (Docker) | `python3 -m unittest discover -s gateway/tests -p "test_gateway.py"` |
| Environnements Python de test des services | créer un venv hors dépôt puis `pip install --require-hashes --only-binary :all: -r requirements-dev.txt` dans `services/<service>` |

