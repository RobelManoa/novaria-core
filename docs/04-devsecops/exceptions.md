# Politique de vulnérabilités et exceptions de sécurité

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 20/11/2026 (revue de sécurité CLD-19, section 15)
Issues de suivi : CLD-23 (politique) et CLD-19 (revue des résultats Snyk et SonarQube)
Statut : proposition à valider par les deux membres (relecture de la pull request)

Ce document fixe trois règles : dans quel délai une faille est corrigée, qui accepte une exception, et pendant combien de temps. Il liste aussi les exceptions actives.

Abréviations : CI (Continuous Integration, intégration continue), UTC (temps universel coordonné).

## 1. Principe

| Élément | Règle |
|---|---|
| Seuil bloquant | Une faille de gravité **high** ou **critical** fait échouer le contrôle `snyk` ou `docker` de la CI ; la pull request ne peut pas être fusionnée |
| Corriger d'abord | Une faille avec correctif publié se corrige : mise à jour de la dépendance, de l'image de base ou des paquets système (`apt-get upgrade`, `apk upgrade`) |
| Exception en dernier recours | Une exception n'existe que si **aucun correctif n'est publié** ou si le faux positif est démontré |
| Jamais d'exception | Pour un secret détecté par `gitleaks` : le secret est révoqué et remplacé, quelle que soit la gravité. **Seul cas admis : un faux positif démontré** (valeur d'essai fabriquée, sans valeur d'accès, donc rien à révoquer) dont l'historique ne peut pas être réécrit ; il est identifié par son empreinte exacte (section 11) |
| Seuil non abaissé | Aucune exception ne passe par une baisse du seuil, l'option `--exclude-base-image-vulns`, une commande forcée en succès ou `continue-on-error` |

## 2. Délais de correction

Le délai court à partir de la date où la faille est connue du binôme (échec de la CI ou du scan hebdomadaire) et où un correctif est publié.

| Gravité | Correctif publié | Aucun correctif publié |
|---|---|---|
| critical | Corrigée avant la fusion, ou sous **7 jours** si découverte par le scan hebdomadaire | Exception de 30 jours au plus, avec ligne dans le registre des risques |
| high | Corrigée avant la fusion, ou sous **14 jours** si découverte par le scan hebdomadaire | Exception de 30 jours au plus, avec ligne dans le registre des risques |
| medium, low | Traitée avec les mises à jour mensuelles de Dependabot (une pull request groupée) | Surveillée, sans exception |

## 3. Qui décide d'une exception

| Étape | Qui |
|---|---|
| Proposer | La personne qui rencontre la faille : une pull request qui modifie `.snyk`, ce document et le registre des risques |
| Décider | L'**autre membre** du binôme, en approuvant la pull request (relecture croisée) ; la session qui a écrit la modification ne l'approuve pas |
| Responsable de l'exception | Manoa Robel (équipe cloud et livraison, issue CLD-23) |
| Information du professeur | Les exceptions actives figurent dans ce document et dans le registre des risques, consultables à chaque jalon |

## 4. Durée maximale

| Règle | Valeur |
|---|---|
| Durée d'une exception | **30 jours** au plus à partir de la date de création |
| Expiration | Toujours **avant le 10/12/2026**, date de la soutenance : la dernière expiration autorisée est le **09/12/2026** |
| Renouvellement | Possible après une nouvelle vérification : correctif publié ou non, avec une nouvelle ligne datée ; sans nouvelle vérification, l'exception expire |
| À l'expiration | Snyk ignore de nouveau l'exception : si la faille persiste, la CI échoue |

## 5. Contenu obligatoire d'une exception

Chaque exception de `.snyk` a ces quatre éléments, vérifiés par un test (section 8) :

| Élément | Où |
|---|---|
| Identifiant Snyk | Clé dans `.snyk`, ligne du tableau de la section 6 |
| Raison (`reason`) | `.snyk`, avec la référence de ce document |
| Expiration (`expires`) | `.snyk` et tableau de la section 6 |
| Entrée au registre des risques | Ligne R10 de `docs/07-gestion/registre-risques.md`, qui cite l'identifiant |

## 6. Exceptions actives

Cinq exceptions au 20/11/2026. SNYK-DEBIAN13-ZLIB-22249554 a été **supprimée** ce jour : corrigée (section 15.2).

| Identifiant Snyk | Composant | Image | Raison | Créée le | Expiration | Registre |
|---|---|---|---|---|---|---|
| SNYK-DEBIAN13-ATTR-17678182 | libattr1 (Link Following) | services Python (python:3.15-slim, Debian 13) | Aucun correctif publié par Debian, revérifié le 15/11/2026 (renouvellement de l'exception du 17/10/2026) | 2026-11-15 | 2026-12-09 | R10 |
| SNYK-DEBIAN13-ACL-17677866 | libacl1 (Link Following) | services Python (python:3.15-slim, Debian 13) | Aucun correctif publié par Debian, revérifié le 15/11/2026 (renouvellement de l'exception du 17/10/2026) | 2026-11-15 | 2026-12-09 | R10 |
| SNYK-DEBIAN13-SQLITE3-22119065 | libsqlite3-0 (Out-of-bounds Write) | services Python (python:3.15-slim, Debian 13) | Aucun correctif publié par Debian à la date de création | 2026-11-03 | 2026-12-03 | R10 |
| SNYK-DEBIAN13-SQLITE3-22119091 | libsqlite3-0 (Out-of-bounds Write) | services Python (python:3.15-slim, Debian 13) | Aucun correctif publié par Debian à la date de création | 2026-11-03 | 2026-12-03 | R10 |
| SNYK-DEBIAN13-SQLITE3-22119098 | libsqlite3-0 (Out-of-bounds Write) | services Python (python:3.15-slim, Debian 13) | Aucun correctif publié par Debian à la date de création | 2026-11-03 | 2026-12-03 | R10 |

## 7. Scan hebdomadaire

| Élément | Valeur |
|---|---|
| Déclencheur | `schedule` dans `.github/workflows/ci.yml` : chaque **lundi à 06:00 UTC** |
| Branche | `main` : GitHub n'exécute un scan planifié que depuis la branche par défaut. Tant que ce fichier n'est pas fusionné dans `main`, le scan ne tourne pas |
| Jobs exécutés | `snyk` (dépendances) et `docker` (construction des images et analyse Snyk). Les autres jobs sont réservés aux pull requests et aux pushes |
| But | Détecter une nouvelle faille d'une image de base ou d'une dépendance sans attendre une pull request |
| Si le scan échoue | La personne responsable (Manoa Robel) ouvre une issue, applique le délai de la section 2 et, sans correctif publié, ajoute une exception selon les sections 3 à 5 |
| Vérification | Onglet Actions de GitHub, workflow CI, événement `schedule` |

## 8. Contrôle automatique

Le test `scripts/dev/test_exceptions.py` vérifie que chaque exception de `.snyk` :

- a une raison et une expiration ;
- expire avant le 10/12/2026 et au plus 30 jours après sa création ;
- figure dans le tableau de la section 6 avec la même expiration ;
- est citée dans le registre des risques.

Depuis CLD-19, le même test vérifie aussi :

- que chaque `# noqa` d'une règle de sécurité (`S…`, `BLE001`) porte sa raison sur la ligne ou dans le commentaire qui la précède ;
- qu'aucun marqueur de désactivation (`NOSONAR`, `nosemgrep`, `eslint-disable`, `@ts-ignore`, `@ts-expect-error`, `# nosec`) n'apparaît dans le code, et que `sonar-project.properties` n'ignore aucune règle ;
- que chaque règle SonarQube de la section 15.3 est « Corrigé » ou « Justifié » avec une raison, et qu'une exception justifiée expire au plus tard le 09/12/2026.

| Linux (bash) | Windows (PowerShell) |
|---|---|
| `python3 -m unittest discover -s scripts/dev` | `py -3 -m unittest discover -s scripts/dev` |

## 9. Revue et suppression

| Moment | Action |
|---|---|
| Avant l'expiration | Reconstruire l'image backend (la ligne `apt-get upgrade` du Dockerfile récupère les correctifs publiés) et relancer l'analyse |
| Faille corrigée | Supprimer l'exception de `.snyk` et sa ligne du tableau de la section 6, puis noter la fermeture (date, version corrigée) dans la ligne R10 du registre des risques |
| Faille toujours sans correctif | Renouveler selon la section 4 |
| Fin de projet | Aucune exception ne doit rester active après le 09/12/2026 |

## 10. Revue du 27/10/2026

| Vérification | Résultat |
|---|---|
| Image de base du backend | `python:3.15-slim` (Debian 13 « trixie »). Dependabot l'a fait passer de `python:3.12-slim` à `python:3.15-slim` le 26/10/2026 (#163). Les exceptions ont été créées sur l'ancienne image : elles visent des paquets Debian, identiques dans la nouvelle |
| Versions installées après `apt-get upgrade` | zlib1g `1:1.3.dfsg+really1.3.1-1+b1`, libattr1 `1:2.5.2-3`, libacl1 `2.3.2-2+b1` : mêmes versions avant et après la mise à jour, donc aucun correctif reçu |
| Correctif publié par Debian 13 | **Non** pour les trois failles. Pages Snyk lues le 27/10/2026 : « There is no fixed version for `Debian:13` » pour `zlib` (CVE-2026-85091), `attr` (CVE-2026-54371) et `acl` (CVE-2026-54369). Les numéros CVE sont ceux des pages Snyk, non recoupés avec le suivi de sécurité de Debian |
| Dernier contrôle des images sur `main` (push du 26/10/2026, 21:04 UTC) | Job `docker` réussi : backend « Tested 88 dependencies, no vulnerable paths found », frontend « Tested 21 dependencies, no vulnerable paths found » |
| Premier scan planifié sur `main` | Exécution `schedule` du 26/10/2026, démarrée à 12:16 UTC (run 40321302551) : jobs `docker` et `snyk` réussis, les quatre autres jobs ignorés comme prévu. L'heure prévue est 06:00 UTC ; GitHub ne garantit pas l'heure exacte d'un scan planifié |
| Les exceptions sont-elles encore nécessaires pour que le contrôle réussisse ? | **Non vérifié** : le journal de Snyk n'affiche pas les failles ignorées. À contrôler avant le 15/11/2026 (commande ci-dessous) |

Décision : les trois exceptions sont **maintenues** (aucun correctif publié), sans changement de date. Prochaine revue avant le 15/11/2026 : si la commande ci-dessous ne signale plus ces trois failles sans la politique, supprimer les exceptions (section 9).

| Contrôle de nécessité (même commande sous Linux et Windows) | Effet |
|---|---|
| `docker build -t novaria-traitement:test services/traitement` puis `snyk container test novaria-traitement:test --file=services/traitement/Dockerfile --severity-threshold=high` | Sans `--policy-path`, Snyk n'applique pas `.snyk` : il liste les failles de gravité high ou critical. Demande `snyk auth` (jeton saisi dans le navigateur, jamais dans le terminal ni dans une conversation) |

## 11. Faux positifs de gitleaks

`gitleaks` lit **tout l'historique** : une valeur qui ressemble à une clé reste signalée dans le commit qui l'a introduite, même corrigée ensuite, et l'historique d'une branche protégée ne se réécrit pas (jamais de `push --force`). Un faux positif démontré s'écarte donc par son **empreinte exacte** dans `.gitleaksignore`, à la racine :
aucune règle n'est désactivée, aucun chemin n'est exclu, la commande de la CI ne change pas (un test le vérifie), et toute autre détection fait toujours échouer le contrôle.

| Empreinte | Fichier | Règle | Ce que c'est | Date | Décision |
|---|---|---|---|---|---|
| `2dc8754e130c9c84f5e92e5fe5558d5978cb9975:services/traitement/tests/fakes.py:generic-api-key:16` | `services/traitement/tests/fakes.py`, ligne 16 | `generic-api-key` | Clé de signature d'**essai** des tests d'authentification (BE-03), fabriquée pour les tests, jamais utilisée ailleurs : aucune valeur d'accès, **rien à révoquer**. Le code est corrigé (la valeur est désormais assemblée et ne ressemble plus à une clé) ; seul le commit `2dc8754`, déjà dans `dev`, la contient encore | 2026-10-31 | Proposée par Daddy Luciano ; **accord écrit de Manoa Robel : [À COMPLÉTER] (approbation de la pull request)** |
| `75a1af5ac4cf6e30060607fa358e78fa781057e5:ml/evaluation/sumo.json:sumologic-access-token:250` | `ml/evaluation/sumo.json`, ligne 250 | `sumologic-access-token` | **Empreinte SHA-256 d'un fichier de configuration de SUMO** (un simulateur de trafic, IA-11), écrite par le manifeste d'un run sous la clé `run.sumocfg` : la règle lit « sumo… : 64 caractères » comme un jeton Sumo Logic. Ce n'est qu'un condensat public d'un fichier du dépôt, sans valeur d'accès : **rien à révoquer**. Le code est corrigé (la clé est désormais `run.cfg`, un test vérifie qu'aucune empreinte ne ressemble plus à un jeton) ; seul le commit `75a1af5` (squash de la pull request #282, déjà dans `dev-ia`) la contient encore. Le commit d'origine `71ffe15` n'existe que dans une branche locale | 2026-11-18 | Proposée par Manoa Robel ; **accord écrit de Daddy Luciano : [À COMPLÉTER] (approbation de la pull request)** |

Règles : une ligne par faux positif, jamais une empreinte pour un vrai secret (un vrai secret est révoqué) ; la ligne est retirée de `.gitleaksignore` quand le commit disparaît de l'historique (squash dans `main`). Le même contrôle que la section 3 s'applique : l'**autre** membre approuve.

## 12. Revue du 03/11/2026 : libsqlite3-0 (échec du contrôle `docker`)

Abréviation : CVE (Common Vulnerabilities and Exposures, identifiant public d'une faille).

| Vérification | Résultat |
|---|---|
| Ce qui échoue | Le job `docker` : `snyk container test` signale des failles **high** de `sqlite3/libsqlite3-0` (Out-of-bounds Write) dans l'image de base `python:3.15-slim` de **quatre services** (alerte, collecte, reponse, traitement). L'image du front-end est saine (« Tested 21 dependencies, no vulnerable paths found ») |
| Où | Scan planifié de `main` (run 125344230302, 3 failles par image) et pull requests Dependabot #208 et #209 (runs 124945854978 et 124948575087, 4 failles par image) |
| Failles | SNYK-DEBIAN13-SQLITE3-22119065 (CVE-2026-119373), SNYK-DEBIAN13-SQLITE3-22119091 (CVE-2026-119374) et SNYK-DEBIAN13-SQLITE3-22119098 (CVE-2026-119379). Publiées le 30/10/2026 d'après Snyk. Numéros CVE lus sur les pages Snyk, **non recoupés avec le suivi de sécurité de Debian** |
| Faille non retenue | SNYK-DEBIAN13-SQLITE3-22119092 (CVE-2026-119586) figurait dans les scans des pull requests, **pas dans celui de `main`**, plus récent. Aucune exception n'est créée pour elle ; la page Snyk lue le 03/11/2026 ne porte pas la mention « no fixed version ». À surveiller : si elle revient, la traiter selon les sections 2 à 5 |
| Chemin | `util-linux/liblastlog2-2` dépend de `libsqlite3-0` : le paquet ne se retire pas de l'image sans casser la chaîne `util-linux` |
| Correctif publié par Debian 13 | **Non**. Pages Snyk lues le 03/11/2026 : « no fixed version for `Debian:13` `sqlite3` » pour les trois failles. Dans une image `python:3.15-slim` tirée le 03/11/2026, après `apt-get update` : `libsqlite3-0` installé `3.46.1-7+deb13u2` = version candidate `3.46.1-7+deb13u2`, donc `apt-get upgrade` (déjà dans les Dockerfile) ne change rien ; seul `tzdata` est mis à jour |
| Les exceptions suffisent-elles ? | **Non vérifié** : la CLI Snyk n'est pas installée sur le poste de cette revue et le journal de Snyk n'affiche pas les failles ignorées. La preuve sera le job `docker` vert après fusion |

Décision proposée : trois exceptions de 30 jours (création le 03/11/2026, expiration le **03/12/2026**, avant le 10/12/2026), à approuver par l'**autre membre** du binôme (section 3). Les trois exceptions du 17/10/2026 expirent toujours le 15/11/2026 : elles se renouvellent séparément, après une nouvelle vérification (section 4).

## 13. Revue du 05/11/2026 : nouvelle faille de zlib1g (échec du contrôle `docker`)

| Vérification | Résultat |
|---|---|
| Ce qui échoue | Le job `docker` de la pull request #219 (MS-09 et MS-10) : `snyk container test` signale une faille **high** de `zlib/zlib1g` (Out-of-bounds Write) dans l'image de base `python:3.15-slim` des **quatre services Python** (alerte, collecte, reponse, traitement), « found 1 issue » par image. L'image du front-end est saine. La pull request ne change pas l'image de base : la cause n'est pas son code |
| Faille | SNYK-DEBIAN13-ZLIB-22249554 (CVE-2026-76844, CWE-787), introduite le 24/08/2026 d'après Snyk. Numéro CVE lu sur la page Snyk, **non recoupé avec le suivi de sécurité de Debian**. Elle s'ajoute à SNYK-DEBIAN13-ZLIB-19520500 (même paquet, autre faille, exception du 17/10/2026) |
| Correctif publié par Debian 13 | **Non**. Page Snyk lue le 05/11/2026 : « There is no fixed version for Debian:13 zlib ». Dans une image `python:3.15-slim` tirée le 05/11/2026, après `apt-get update` : `zlib1g` installé `1:1.3.dfsg+really1.3.1-1+b1`, et `apt-get -s upgrade` ne propose aucune mise à jour de `zlib1g` : la ligne `apt-get upgrade` des Dockerfile ne change rien |
| Chemin | `zlib1g` est nécessaire à `dpkg` et `apt` : le paquet ne se retire pas de l'image |
| Les exceptions suffisent-elles ? | **Non vérifié** : la CLI Snyk n'est pas installée sur le poste de cette revue. La preuve sera le job `docker` vert après fusion |

Décision proposée : une exception de 30 jours (création le 05/11/2026, expiration le **05/12/2026**, avant le 10/12/2026), à approuver par l'**autre** membre du binôme (section 3). Elle se renouvelle séparément, après une nouvelle vérification (section 4).

**Correction du 20/11/2026 (CLD-19).** Cette revue a rangé SNYK-DEBIAN13-ZLIB-22249554 parmi les failles « Out-of-bounds Write » (CWE-787) et lui a donné le numéro CVE-2026-76844. Le suivi de sécurité de Debian attribue ce numéro à `webpack-dev-middleware`, pas à zlib, et la page de Snyk l'intitule aujourd'hui « Directory Traversal in zlib » (CWE-22) avec un correctif publié : voir la section 15.2. Cette exception est supprimée.

## 14. Revue du 15/11/2026 : expiration des exceptions du 17/10/2026 (échec des contrôles `docker` de `main` et de la pull request #257)

| Vérification | Résultat |
|---|---|
| Ce qui échoue | Les trois exceptions du 17/10/2026 (zlib1g, libattr1, libacl1) expirent le **15/11/2026**. Le job `docker` du push sur `main` (15/11/2026, 15:09 UTC) et celui de la pull request #257 (Dependabot, `dnspython` dans `data/etl`) échouent : `snyk container test` signale deux failles **high** (`attr/libattr1`, `acl/libacl1`, Link Following) dans l'image `python:3.15-slim` des **quatre services Python**. L'image du front-end est saine. La pull request #257 ne change pas l'image de base : la cause n'est pas son code |
| Failles | SNYK-DEBIAN13-ATTR-17678182 et SNYK-DEBIAN13-ACL-17677866 |
| zlib1g, SNYK-DEBIAN13-ZLIB-19520500 | **Corrigée.** Dans `python:3.15-slim` tirée le 15/11/2026, après `apt-get update`, `apt-get changelog zlib1g` montre la version `1:1.3.dfsg+really1.3.1-1+deb13u1` (trixie-security, 01/11/2026) qui corrige CVE-2026-85091 (le numéro CVE vient de la page Snyk lue le 27/10/2026, section 10). La ligne `apt-get upgrade` des Dockerfile l'installe, et le journal du 15/11/2026 ne signale plus cette faille. **Exception supprimée** (section 9) |
| zlib1g, SNYK-DEBIAN13-ZLIB-22249554 | **Non corrigée** d'après le même changelog, qui ne cite pas CVE-2026-76844. Exception du 05/11/2026 conservée, sans changement (expiration le 05/12/2026) |
| libattr1 et libacl1 | `apt-cache policy` après `apt-get update` : installée = candidate (`1:2.5.2-3` et `2.3.2-2+b1`). **Aucune mise à jour publiée** par Debian 13. Les pages Snyk n'ont pas été relues ce jour (le quota d'essais privés de Snyk est atteint) : la vérification est celle de la version installée |
| Les exceptions suffisent-elles ? | **Non vérifié** : la CLI Snyk n'est pas installée sur le poste de cette revue, et le quota de Snyk est atteint. La preuve sera le job `docker` vert après fusion |

Décision proposée : suppression de l'exception ZLIB-19520500 ; renouvellement de ATTR-17678182 et ACL-17677866 pour une durée de 24 jours (création le 15/11/2026, expiration le **09/12/2026**, dernier jour autorisé, section 4), à approuver par l'**autre** membre du binôme (section 3). Un nouveau renouvellement n'est pas possible après le 09/12/2026 (section 9) : sans correctif de Debian à cette date, il faut une autre solution (changer d'image de base, par exemple) et la décider avant.

Autre point constaté le même jour : le contrôle `snyk` (dépendances) échoue aussi sur la pull request #257 avec le message « You have used your limit of private tests » : c'est le **quota mensuel de 200 essais privés** de l'organisation Snyk, pas une faille. Aucun changement de contrôle n'est proposé ici (section 6 de `CLAUDE.md`) ; voir la décision à prendre dans la description de la pull request.

## 15. Revue de sécurité du 20/11/2026 (CLD-19) : résultats Snyk et SonarQube triés

Critère de CLD-19 : **les exceptions ont une raison et une date d'expiration.** Cette section trie chaque résultat de gravité haute ou critique de Snyk et de SonarQube : corrigé, ou justifié avec une raison et une expiration. Les exceptions de Snyk sont dans la section 6 ; celles de SonarQube, dans la section 15.3. Aucune exception n'est silencieuse : un test (section 8) refuse une désactivation de contrôle qui n'a pas sa raison.

Abréviations : CVE (Common Vulnerabilities and Exposures, identifiant public d'une faille), CWE (Common Weakness Enumeration, type de faiblesse), SCA (Software Composition Analysis, analyse des dépendances), SAST (Static Application Security Testing, analyse du code source), IaC (Infrastructure as Code), DSA (Debian Security Advisory, bulletin de sécurité de Debian).

### 15.1 Sources et limites

| Source | Lue le 20/11/2026 | Résultat |
|---|---|---|
| CI de `main` | API publique de GitHub, exécution 44702536815 (push de 08:26 UTC) | **15 jobs réussis**, dont `snyk`, `docker`, `sonarqube` et `gitleaks`. L'exécution précédente (07:28) avait échoué sur le test de `collecte` (`service (collecte)`), sans lien avec la sécurité |
| SonarCloud | API publique (`issues/search`, `qualitygates/project_status`, `hotspots/search`), projet `RobelManoa_novaria-core`, branche par défaut | Porte de qualité **réussie** (six conditions sur le code nouveau : fiabilité, sécurité et maintenabilité à A, couverture 94,3 %, duplication 0,5 %, points chauds revus à 100 %). **215 résultats ouverts, tous de type `CODE_SMELL` : 0 `BUG`, 0 `VULNERABILITY`**, 0 point chaud à revoir. Gravité : 1 BLOCKER, 61 CRITICAL, 87 MAJOR, 66 MINOR |
| Snyk | Pages publiques `security.snyk.io`, suivi de sécurité de Debian, installation réelle dans `python:3.15-slim` | **Aucun scan Snyk n'a été lancé** : il demande un jeton (secret, `CLAUDE.md`, section 6). La nécessité de chaque exception repose sur la CI verte, sur les pages de Snyk et de Debian et sur les versions réellement installées |

**Non vérifié** : les alertes Dependabot de GitHub (elles demandent un accès au dépôt) ; le contenu du journal de Snyk dans la CI (il n'affiche pas les failles ignorées).

Seuls les résultats SonarQube de gravité BLOCKER et CRITICAL (62) sont triés ici. Les 153 résultats MAJOR et MINOR sont de la dette de maintenabilité courante, sans effet sur la sécurité ; ils ne font pas l'objet d'une exception.

### 15.2 Snyk : cinq exceptions maintenues, une supprimée

Versions relevées dans une image `python:3.15-slim` tirée le 20/11/2026, après `apt-get update` et `apt-get upgrade -y --no-install-recommends` (la commande des Dockerfile). Colonne Debian : page du paquet source dans le suivi de sécurité de Debian (Debian 13 « trixie »).

| Identifiant Snyk | Debian 13 (suivi de sécurité) | Snyk (page publique) | Version installée après la mise à jour | Décision |
|---|---|---|---|---|
| SNYK-DEBIAN13-ZLIB-22249554 | Les 14 CVE de zlib du suivi sont corrigées pour trixie ou sans état ouvert ; **CVE-2026-76844 n'est pas une faille de zlib** (c'est `webpack-dev-middleware`) | « Upgrade Debian:13 zlib to version 1:1.3.dfsg+really1.3.1-1+deb13u1 or higher » | zlib1g `1:1.3.dfsg+really1.3.1-1+deb13u1` | **Supprimée** : corrigée |
| SNYK-DEBIAN13-ATTR-17678182 (CVE-2026-54371) | trixie « vulnerable (no DSA) » ; corrigée dans forky et sid | « no fixed version for Debian:13 attr » | libattr1 `1:2.5.2-3` (= candidate) | Maintenue, expiration 2026-12-09 |
| SNYK-DEBIAN13-ACL-17677866 (CVE-2026-54369) | trixie « vulnerable (no DSA) » ; corrigée dans forky et sid | « no fixed version for Debian:13 acl » | libacl1 `2.3.2-2+b1` (= candidate) | Maintenue, expiration 2026-12-09 |
| SNYK-DEBIAN13-SQLITE3-22119065 (CVE-2026-119373) | trixie « vulnerable (no DSA) » ; corrigée dans forky et sid | « no fixed version for Debian:13 sqlite3 » | libsqlite3-0 `3.46.1-7+deb13u2` (= candidate) | Maintenue, expiration 2026-12-03 |
| SNYK-DEBIAN13-SQLITE3-22119091 (CVE-2026-119374) | idem | idem | idem | Maintenue, expiration 2026-12-03 |
| SNYK-DEBIAN13-SQLITE3-22119098 (CVE-2026-119379) | idem | idem | idem | Maintenue, expiration 2026-12-03 |

**Pourquoi l'exception de zlib est supprimée.** La mise à jour `1:1.3.dfsg+really1.3.1-1+deb13u1` (sécurité de Debian 13, annoncée le 01/11/2026) est installée par la ligne `apt-get upgrade` des Dockerfile et Snyk la donne comme version corrigée. La revue du 05/11/2026 l'avait créée à raison (la mise à jour n'était pas encore proposée par `apt`). La revue du 15/11/2026 l'a gardée parce que le changelog « ne cite pas CVE-2026-76844 » : ce raisonnement venait d'un mauvais numéro, puisque ce CVE n'appartient pas à zlib. Le numéro que Snyk affiche sur cette entrée est lui-même étrange (sa description est celle du paquet `webpack-dev-middleware`) : une anomalie de la base de Snyk, **non élucidée ici**. Ce qui compte pour la décision est la version corrigée, présente dans l'image.

**Vérification de la suppression** : le job `docker` de la pull request qui la supprime (CI sur les quatre images de services). S'il échoue pour cette faille, l'exception est rétablie avec une nouvelle date (section 4) et cette section est corrigée.

**Suite pour les cinq autres** : les trois failles de `libsqlite3-0` expirent le 03/12/2026. À cette date, après une nouvelle vérification (même procédure), elles se renouvellent pour **6 jours au plus** (jusqu'au 09/12/2026, section 4) ou se suppriment si Debian a publié un correctif. Les deux failles de `libattr1` et `libacl1` expirent le 09/12/2026 : pas de renouvellement possible (section 9).

### 15.3 SonarQube : 62 résultats BLOCKER et CRITICAL

| Règle | Nombre | Décision | Raison | Expiration |
|---|---|---|---|---|
| python:S1192 | 10 | Corrigé | Un littéral répété (« Alerte inconnue. », « /api/v1 », « | Méthode | »…) est devenu une constante de module, dans 9 fichiers (`services/alerte`, `services/reponse`, `services/traitement`, `ml/`). Comportement identique : tests des services `alerte` (464) et `reponse` (391) verts ; les rapports générés de `ml/` sont inchangés | sans objet |
| python:S5655 | 1 | Corrigé | `services/traitement/app/flux/classifier.py:98` : la variable `current` est annotée `Hysteresis`. C'était un faux positif de typage (`dataclasses.replace` rend un type que l'analyseur n'infère pas). Il peut rester signalé au prochain scan ; la décision est alors « justifié » avec cette raison | sans objet |
| python:S8414 | 1 | Justifié | BLOCKER, `services/traitement/app/main.py:37` : « ajouter `CORSMiddleware` en dernier ». Les deux couches placées **à l'extérieur** de CORS, `SecurityHeadersMiddleware` et `MetricsMiddleware`, ne refusent jamais une requête : la première ne fait qu'ajouter des en-têtes de sécurité, la seconde ne fait que compter. Le but de la règle (qu'aucune couche ne rejette une pré-vérification avant CORS) est donc atteint. L'ordre est voulu : une pré-vérification `OPTIONS` et chaque erreur portent ainsi aussi les en-têtes de sécurité (BE-08). Pré-vérifications couvertes par `services/traitement/tests/unit/test_cors.py` | 2026-12-09 |
| python:S5754 | 1 | Justifié | `services/collecte/app/adapters/kafka_publisher.py:49` : `except BaseException` qui confie l'erreur à un `Future`. Même schéma que `concurrent.futures` de la bibliothèque standard : le `Future` doit **toujours** se résoudre, sinon l'appelant attendrait sans fin si le fil s'arrête par `SystemExit` ou `KeyboardInterrupt`. L'erreur n'est pas avalée : elle ressort à l'appelant. La suppression `# noqa: BLE001` de la ligne porte la même raison | 2026-12-09 |
| python:S3776 | 19 | Justifié | Complexité cognitive de 16 à 26 (seuil 15) dans 19 fonctions : `ml/` (13 : `prevision/rapport.py` ×2, `prototype_sumo/` ×3, `jeu_entrainement/` ×3, `anomalies/variables.py`, `mesures/__main__.py`, `preparation/ajustement.py`, `registre/documents.py`, `stockage/objets.py`), `data/bigdata/bigdata/generer.py` (2) et `services/traitement/app/` (4 : `flux/classifier.py`, `flux/cleaning.py`, `flux/windows.py`, `api/responses.py`). Dette de **maintenabilité**, pas une faille (aucun résultat de type `BUG` ou `VULNERABILITY`). Ces fonctions sont couvertes par des tests ; en refactorer dix-neuf à moins de trois semaines de la soutenance risque plus (régression sur du code qui marche) qu'il ne rapporte. Refactoring reporté après le 10/12/2026 | 2026-12-09 |
| typescript:S3776 | 1 | Justifié | `frontend/src/services/alertStream.ts:27` : complexité 19 (seuil 15), lecteur du flux d'alertes (SSE) couvert par `frontend/tests/services/alertStream.test.ts`. Même raison que ci-dessus | 2026-12-09 |
| plsql:S1192 | 29 | Justifié | Un seul fichier, `data/dwh/sql/kpi/controle/verifier.sql` (241 lignes) : un script `psql` de contrôle (`\set`, `BEGIN` puis annulation) que SonarCloud analyse comme du PL/SQL. Les « littéraux dupliqués » sont les **valeurs du jeu de contrôle** (identifiants de tronçons, états, dates) calculé à la main dans [kpi.md](../03-donnees/kpi.md), section 4 : les remplacer par des constantes rendrait ce jeu illisible et affaiblirait le contrôle | 2026-12-09 |

Total : **11 corrigés, 51 justifiés**. Aucune exception ne dépasse le 09/12/2026 (section 4). Aucune règle n'est désactivée dans `sonar-project.properties` et aucune ligne ne porte de marqueur `NOSONAR`.

**Résolution dans SonarCloud.** Les 51 résultats justifiés restent **ouverts et visibles** dans SonarCloud tant qu'un membre connecté ne les marque pas « Accepted » (ou « Won't fix ») avec la raison ci-dessus : cette session n'a pas de jeton SonarCloud et n'a rien masqué. Ce marquage est à faire avant le 09/12/2026.

### 15.4 Désactivations de contrôles : inventaire au 20/11/2026

| Mécanisme | Nombre | Où et raison | Contrôle |
|---|---|---|---|
| `continue-on-error`, `\|\| true` (workflows), `--no-verify`, `--exclude-base-image-vulns`, `NOSONAR`, `# nosec`, `nosemgrep`, `eslint-disable`, `@ts-ignore`, `@ts-expect-error` | **0** | Aucun | `scripts/dev/test_exceptions.py` échoue si l'un d'eux apparaît |
| `# noqa` pour une règle de sécurité (`S…`) ou une exception trop large (`BLE001`) | 69 | Chacun porte sa raison sur la ligne ou dans le commentaire qui précède. **19 n'en avaient aucune** (adresses locales de `scripts/dev/`, XML produit par notre SUMO, adresses du jeu ouvert de Paris, dispersion des reprises) et **2 ne l'avaient que quelques lignes plus haut** (`data/etl`, S608) : la raison a été écrite sur la ligne le 20/11/2026 | `test_exceptions.py` échoue pour un nouveau `# noqa` de sécurité sans raison |
| Règles `ruff` ignorées par fichier (`pyproject.toml`) | 3 familles | `S101` (assert) dans les tests ; `S105` et `S106` (secrets d'essai) dans les tests des services qui en ont besoin ; `S608` dans `services/alerte/app/adapters/postgres_store.py` (noms de colonnes constants, valeurs passées en paramètres). Raison écrite dans le fichier | Revue de pull request |
| Exceptions Snyk (`.snyk`) | 5 | Section 6 | `test_exceptions.py` (raison, expiration, registre) |
| Faux positifs de gitleaks (`.gitleaksignore`) | 2 | Section 11 (empreinte exacte, aucune règle désactivée) | Test de la commande de la CI |
| `sonar.exclusions` et `sonar.cpd.exclusions` | voir `sonar-project.properties` | Code généré (`frontend/src/types/api/`), migrations, et code **copié à l'identique** entre services (journaux, redaction, erreurs, jetons) dont l'identité est vérifiée par `scripts/dev/test_gabarit.py`. Raison en commentaire dans le fichier | Toute modification demande l'accord écrit des deux membres (`CLAUDE.md`, section 6) |
| `# type: ignore` (typage) | 47 | Aucune règle de sécurité : 17 dans `scripts/dev/flux_complet.py`, le reste dans les services (couches ASGI et gestionnaires d'erreurs) et les tests | Aucun |

### 15.5 Ce que les contrôles ne couvrent pas

Un contrôle qui ne regarde pas une partie du dépôt ne la déclare pas saine. Ces zones sont **hors périmètre**, aujourd'hui, de la CI :

| Contrôle | Couvre | Ne couvre pas |
|---|---|---|
| Snyk, dépendances (`snyk test`) | `requirements.txt` des quatre services (pas le gabarit) et le `package-lock.json` du front-end | `data/etl`, `data/bigdata`, `ml/` (et `ml/sumo`), `automation/rpa` |
| Snyk, images (`snyk container test`) | Les images des quatre services et du front-end | Les images `simulator`, `data/bigdata` et `ml/sumo`, et les images amont `apache/kafka`, `mongo`, `postgres` et `nginx-unprivileged` (passerelle) |
| Snyk, IaC | `infra/terraform` | Les Dockerfile, `docker-compose.yml` et les workflows |
| Snyk, code (SAST) | Tout le dépôt, **sur `main` seulement** (100 essais par mois) | Les pull requests |
| SonarCloud | `services`, `frontend/src`, `frontend/tests`, `data`, `ml` | `simulator`, `automation`, `scripts`, `gateway` |
| `ruff` avec les règles de sécurité `S` | `services/*` | `scripts/`, `ml/`, `data/`, `simulator/`, `automation/` : les `# noqa: S…` de ces dossiers y suppriment un contrôle que la CI ne lance pas ; au moins 15 constats `ruff` (`S603`, `S607`, `S608`, `S110`) dans huit fichiers de `scripts/dev/` ne sont pas triés |

Étendre ces périmètres modifie la CI : **décision des deux membres, non prise ici** (`CLAUDE.md`, section 6).

### 15.6 Décisions et suite

| Point | État |
|---|---|
| Supprimer l'exception de zlib (corrigée) | Fait dans cette pull request ; vérification par son job `docker` |
| Corriger ce qui se corrige sans risque (11 résultats Sonar, 21 suppressions sans raison sur la ligne) | Fait |
| Marquer les 51 résultats Sonar justifiés dans SonarCloud | À faire par un membre connecté, avant le 09/12/2026 |
| Renouveler ou supprimer les trois exceptions de `libsqlite3-0` | Le 03/12/2026, après vérification (6 jours au plus) |
| Étendre le périmètre de Snyk, de SonarCloud et de `ruff` | À décider à deux ; non fait |
| Prochaine revue | 03/12/2026 |
