# Tests, intégration en conteneur et couverture du back-end (BE-07)

Issue BE-07 (#67). Critère : le Quality Gate de couverture passe. Preuve : le rapport de couverture de la section 3. Exigence EXG-NFR-10.

Abréviations : **CI** (Continuous Integration, intégration continue), **Quality Gate** (seuil de qualité de SonarQube Cloud), **ETL** (Extract, Transform, Load, chargement de données).

## 1. Les trois niveaux de tests

| Niveau | Où | Besoin | Dans la CI |
|---|---|---|---|
| Unitaire et contrat | `services/*/tests/unit`, `tests/contract` | Rien : bases remplacées par des dépôts en mémoire | Oui (`pytest` de chaque service) |
| Intégration PostgreSQL | `services/traitement/tests/integration/test_*_postgres.py` | PostgreSQL 16 | Ignoré (aucune base) |
| Intégration MongoDB | `.../test_audit_mongo.py` | MongoDB 7 avec le script d'initialisation du dépôt | Ignoré |
| Intégration des deux | `.../test_stack_integration.py` | Les deux | Ignoré |

Un test d'intégration est **ignoré** (et non en échec) quand ses variables d'environnement manquent : la CI et un poste sans Docker restent verts. Pour les exécuter, une seule commande monte les deux bases en conteneur.

## 2. Lancer les tests d'intégration en conteneur

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Tout (unitaires + intégration + couverture) | `python3 scripts/dev/dev.py test-integration` ou `make test-integration` | `py -3 scripts/dev/dev.py test-integration` |
| Un sous-ensemble | `python3 scripts/dev/dev.py test-integration -- -k audit --no-cov` | `py -3 scripts/dev/dev.py test-integration -- -k audit --no-cov` |
| Garder les conteneurs | `... test-integration --keep` | `... test-integration --keep` |

Prérequis : `.env` créé (`init-env`), Docker démarré, et les paquets de `services/traitement/requirements-dev.txt` dans l'interpréteur qui lance `dev.py` (`dev-deps` les installe).

Ce que fait la commande :

1. choisit un **projet Compose jetable** (`novaria-it-<6 chiffres hexadécimaux>`) et deux **ports libres** : les bases et les données du poste ne sont pas touchées ;
2. démarre PostgreSQL et MongoDB (`up -d --wait`) ; le script d'initialisation de MongoDB crée les collections, validateurs, index, rôles et comptes de service ;
3. passe à pytest, **par l'environnement et non par la ligne de commande**, trois adresses : `NOVARIA_TEST_POSTGRES_ADMIN_URL` (chaque test crée puis supprime sa propre base), `NOVARIA_TEST_MONGO_URL` (le compte `svc_backend`, avec ses droits de production) et `NOVARIA_TEST_MONGO_ADMIN_URL` (efface les traces d'essai) ;
4. lance toute la suite de `services/traitement` ;
5. supprime le projet, volumes compris (`down -v`), même si un test échoue ou si le démarrage échoue.

Avec une barrière de couverture active, un sous-ensemble de tests ne peut pas atteindre 70 % : ajouter `--no-cov` (ou `--cov-fail-under=0`) pour un sous-ensemble.

## 3. Rapport de couverture

Exécution du 04/11/2026, `dev.py test-integration`, poste Windows 11, Docker Desktop, PostgreSQL 16 et MongoDB 7 en conteneur, couverture avec **branches** :

```text
991 passed, 12 warnings in 277.08s (0:04:37)
Name                                       Stmts   Miss Branch BrPart  Cover   Missing
app/__init__.py                                0      0      0      0   100%
app/api/__init__.py                            0      0      0      0   100%
app/api/deps.py                               35      0      4      0   100%
app/api/responses.py                          24      0     12      0   100%
app/api/v1/__init__.py                         0      0      0      0   100%
app/api/v1/auth.py                            21      0      0      0   100%
app/api/v1/health.py                           8      0      0      0   100%
app/api/v1/indicators.py                      45      0      6      0   100%
app/api/v1/users.py                           36      0      2      0   100%
app/cli.py                                    51      0      4      0   100%
app/core/__init__.py                           0      0      0      0   100%
app/core/audit.py                             44      0     10      0   100%
app/core/config.py                            27      0      2      0   100%
app/core/errors.py                           123      0     52      0   100%
app/core/logs.py                              67      0     10      0   100%
app/core/routing.py                           22      0      6      0   100%
app/core/security.py                          39      0      0      0   100%
app/core/unhandled.py                         27      0      6      0   100%
app/core/versioning.py                        25      0     10      0   100%
app/db/__init__.py                             0      0      0      0   100%
app/db/migration.py                           11      0      2      0   100%
app/db/observer.py                            16      0      2      0   100%
app/db/session.py                             40      0      4      0   100%
app/main.py                                   21      0      0      0   100%
app/models/__init__.py                         3      0      0      0   100%
app/models/base.py                             6      0      0      0   100%
app/models/user.py                            21      0      0      0   100%
app/repositories/__init__.py                   0      0      0      0   100%
app/repositories/audit.py                     28      0      4      1    97%   39->exit
app/repositories/indicators.py                64      0     14      0   100%
app/repositories/users.py                     37      0      6      0   100%
app/schemas/__init__.py                        0      0      0      0   100%
app/schemas/errors.py                         13      0      0      0   100%
app/schemas/events.py                        238      0     32      0   100%
app/schemas/indicators.py                     35      0      0      0   100%
app/schemas/users.py                          23      0      0      0   100%
app/services/__init__.py                       0      0      0      0   100%
app/services/audit.py                         63      0     12      0   100%
app/services/auth.py                          44      0      8      0   100%
app/services/indicators.py                    66      0     14      0   100%
app/services/users.py                         37      0      0      0   100%
migrations/env.py                             32      0      6      0   100%
migrations/versions/0001_utilisateurs.py      11      0      0      0   100%
TOTAL                                       1403      0    228      1    99%
Coverage XML written to file coverage.xml
Required test coverage of 70.0% reached. Total coverage: 99.94%
```

Résumé par ensemble (barrière de 70 % atteinte partout) :

| Ensemble | Tests | Instructions | Branches | Couverture | Mesure |
|---|---|---|---|---|---|
| `services/traitement` avec les deux bases | 991 réussis, 0 ignoré | 1 403 | 228 | **99,94 %** | `dev.py test-integration` |
| `services/traitement` sans base (comme la CI) | 908 réussis, 83 ignorés | 1 403 | 228 | 99,20 % | `pytest` |
| `services/collecte`, `alerte`, `reponse` | 139 réussis chacun | 335 | 42 | 100 % | `pytest` |
| `services/_gabarit` | 138 réussis, 1 ignoré | 335 | 42 | 100 % | `pytest` |
| `data/etl` | 189 réussis, 3 ignorés | 1 174 | 234 | 96 % | `coverage run` |

La seule branche partielle restante, `app/repositories/audit.py` 39→exit, est la sortie d'une boucle de deux essais dont la seconde lève toujours : elle ne peut pas être atteinte.

Ce que l'intégration ajoute à la couverture sans base : 8 instructions de `migrations/env.py` (la migration lancée depuis `APP_DATABASE_URL`, comme `dev.py db-migrate-app`) et la ligne `sys.exit(main())` de `app/cli.py`.

## 4. La barrière de couverture

| Où | Quoi | Effet |
|---|---|---|
| `pyproject.toml` de chaque service et du gabarit | `[tool.coverage.report] fail_under = 70` et `[tool.coverage.run] branch = true` | `pytest` échoue sous 70 % ; le job `service` de la CI, donc le contrôle obligatoire `backend`, échoue avec lui |
| `data/etl/pyproject.toml` | Idem | `coverage xml` échoue sous 70 % ; le job `etl` de la CI échoue |
| SonarQube Cloud (`sonar-project.properties`) | `sonar.qualitygate.wait=true` ; lit `services/*/coverage.xml` et `data/etl/coverage.xml` | Le Quality Gate de SonarQube décide de la fusion (contrôle obligatoire `sonarqube`) |

Preuve que la barrière est active : `pytest tests/unit/test_health.py` dans `services/collecte` (couverture 27 %) répond `FAIL Required test coverage of 70.0% not reached. Total coverage: 27.06%` et sort avec le code 1. Pour l'ETL, `coverage xml` après un seul fichier de tests répond `Coverage failure: total of 0 is less than fail-under=70` (code 2) ; après la suite complète, code 0.

**Non vérifié ici** : le résultat du Quality Gate de SonarQube Cloud lui-même (sa configuration est dans le projet SonarQube, pas dans le dépôt, et aucune exécution de la CI n'a été lue pour BE-07). Le seuil de 70 % du dépôt est le plancher que le code garantit avant même SonarQube ; le Quality Gate par défaut de SonarQube mesure en plus la couverture du code **nouveau**.

Un service créé par `dev.py new-service` hérite de la barrière (copie du gabarit).

## 5. Ce que prouvent les tests d'intégration ajoutés par BE-07

| Test | Preuve |
|---|---|
| `test_upgrade_reads_the_address_of_the_database_from_the_environment` | `alembic upgrade head` lancé comme en exploitation (adresse lue dans `APP_DATABASE_URL`, sans connexion fournie) crée le schéma `app` |
| `test_upgrading_twice_from_the_environment_changes_nothing` | Deux `upgrade` de suite ne changent rien ; `downgrade base` retire la table |
| `test_the_logging_of_alembic_is_configured_from_the_ini_file_and_restored` | Le fichier `alembic.ini` configure les journaux sans casser ceux de l'application |
| `test_every_call_of_a_real_account_is_audited_in_mongodb_under_its_identifier` | Compte lu dans le vrai PostgreSQL (mot de passe vérifié en argon2id), jeton réel, et chaque appel laisse dans le vrai MongoDB une entrée sous l'identifiant de ce compte ; ni nom, ni mot de passe, ni jeton dans l'audit |
| `test_a_refused_login_against_the_real_database_is_audited_as_anonymous` | Compte inconnu et mot de passe faux : même réponse, deux entrées `anonymous` `denied` |
| `test_when_mongodb_fails_the_accounts_still_work` | L'audit est au mieux : l'échec de MongoDB ne change aucune réponse |

## 6. Proposition pour la CI (non appliquée)

Aujourd'hui la CI exécute `pytest` sans base : 83 tests d'intégration sont ignorés. Un job d'appui pourrait lancer `dev.py test-integration` sur le runner (Docker y est installé) et déposer `coverage.xml` en artefact, sans que `sonarqube` l'attende. **Je ne l'ai pas ajouté** : `scripts/dev/test_ci.py` fixe la liste exacte des jobs (`JOBS_D_APPUI`) et interdit de nommer un service dans `ci.yml`. Ajouter ce job oblige à modifier ce test, donc un contrôle de la CI, ce que `CLAUDE.md` n'autorise qu'avec l'accord écrit des deux membres.

Job proposé (à placer après `etl`), avec la modification de `JOBS_D_APPUI = {"services", "service", "etl", "integration"}` dans `scripts/dev/test_ci.py` :

```yaml
  integration:
    if: ${{ github.event_name != 'schedule' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with: { python-version: "3.12", cache: pip, cache-dependency-path: "services/*/requirements*.txt" }
      - run: pip install -r services/traitement/requirements-dev.txt
      - run: python scripts/dev/dev.py init-env
      - run: python scripts/dev/dev.py test-integration
      - uses: actions/upload-artifact@v7
        if: ${{ !cancelled() }}
        with: { name: coverage-integration, path: services/traitement/coverage.xml }
```

Une version très proche de ce job (chemin de cache différent) a passé `actionlint` sur le poste ; il n'a pas été lancé sur un runner GitHub (non vérifié).

## 7. Limites

| Sujet | Position actuelle |
|---|---|
| Intégration dans la CI | Proposée, non appliquée (section 6) |
| Quality Gate de SonarQube | Non lu ici (section 4) |
| Couverture de `services/collecte`, `alerte`, `reponse` | 100 % de squelettes identiques au gabarit : elle ne dit rien de la logique future, qui aura ses propres tests |
| Intégration de Kafka | Hors périmètre de BE-07 (PostgreSQL et MongoDB) ; `dev.py kafka-roundtrip` existe |
| Port libre | Le port est choisi libre puis rendu au système avant le démarrage du conteneur : un autre programme peut le prendre entre-temps (très rare) ; relancer la commande |
| Sous-ensemble de tests | Échoue sur la barrière sans `--no-cov` |
