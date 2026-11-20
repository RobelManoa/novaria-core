# Tableau de bord de pilotage du projet

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsable : Manoa Robel · relecture croisée : Daddy Luciano
Dernière mise à jour : 20/11/2026
Issue de suivi : GES-11 (#97), jalon M5
Statut : à valider par les deux membres (relecture de la pull request)

Critère d'acceptation : **chaque indicateur se recalcule à partir de GitHub.** Preuve : ce document, section 3 (la commande), section 6 (le recalcul à la main) et le bloc mesuré de la section 4.

Abréviations : **API** (Application Programming Interface, interface de programmation), **JSON** (JavaScript Object Notation), **P0** (priorité maximale du backlog), **CI** (Continuous Integration, intégration continue).

## 1. En bref

| Tâche de l'issue | Réalisé | Où |
|---|---|---|
| Indicateurs : exigences vérifiées, risques traités, livrables par jalon | Trois indicateurs, calculés par un outil Python (bibliothèque standard) | [`scripts/github/tableau_de_bord.py`](../../scripts/github/tableau_de_bord.py) |
| Source et calcul de chaque indicateur | Un tableau par indicateur (section 2) | Section 2 |
| Distinguer absence de mesure et résultat nul | Deux états distincts, affichés différemment, testés | Section 5 |

## 2. Les trois indicateurs : source et calcul

| | Exigences vérifiées | Risques traités | Livrables par jalon |
|---|---|---|---|
| **Question** | Combien d'exigences ont leur preuve exécutée ? | Combien de risques ont disparu ? | Où en est chaque jalon, et chaque livrable a-t-il sa preuve dans le dépôt ? |
| **Source** | `docs/02-specifications/exigences.md` (tableau, colonne **État**) | `docs/07-gestion/registre-risques.md` (tableau, colonne **Statut**) | API de GitHub : **issues** et **jalons** (milestones), et arbre des fichiers du dépôt |
| **Calcul** | Lignes `EXG-…` dont l'état commence par **Prouvé**, sur les lignes dont l'état est lisible. Détail par priorité (Doit, Devrait, Pourrait) et par domaine | Lignes `R<n>` dont le statut commence par **Clos**, sur les lignes dont le statut est lisible. Les **Suspendus** sont comptés à part | Par jalon : issues fermées sur issues du jalon. Pour chaque issue fermée, les chemins cités dans la section « Preuve attendue » existent-ils à la révision lue ? |
| **Définition retenue** | « Vérifiée » = **Prouvé** : la preuve attendue existe **et a été exécutée** ([exigences.md](../02-specifications/exigences.md), « Comment lire »). « Partiel » ne compte pas | « Traité » = **Clos** : le risque a disparu, avec une date. **Suspendu** (cause écartée pour le moment, par exemple R3 si AWS n'est pas utilisé) n'est **pas** traité : il peut revenir | « Livrable » = une issue du backlog. Fermée = livrée. Les pull requests ne sont pas des issues et ne sont pas comptées |
| **Lignes écartées** | Une ligne sans état lisible n'est ni comptée « prouvée » ni mise au dénominateur : elle est **listée** | Idem ; un risque sans responsable ou sans action est **listé** (le registre l'interdit) | Une issue sans jalon est comptée à part |

Source de vérité : les documents sont **versionnés dans le dépôt GitHub** et les issues y vivent. L'outil lit les deux fichiers à une révision donnée (`--ref`, `main` par défaut) sur `raw.githubusercontent.com`, et les issues par l'API REST. Rien n'est saisi à la main.

## 3. Recalculer

| Besoin | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Tableau complet, lu sur `main` | `python3 scripts/github/tableau_de_bord.py` | `py -3 scripts/github/tableau_de_bord.py` |
| Lire une autre révision (branche, étiquette, empreinte) | `python3 scripts/github/tableau_de_bord.py --ref dev-ia` | `py -3 scripts/github/tableau_de_bord.py --ref dev-ia` |
| Lire les deux documents dans la copie de travail (avant de pousser), issues toujours sur GitHub | `python3 scripts/github/tableau_de_bord.py --local` | `py -3 scripts/github/tableau_de_bord.py --local` |
| Mesures en JSON | `python3 scripts/github/tableau_de_bord.py --json` | `py -3 scripts/github/tableau_de_bord.py --json` |
| Mettre à jour le bloc mesuré de ce document | `python3 scripts/github/tableau_de_bord.py --ecrire` | `py -3 scripts/github/tableau_de_bord.py --ecrire` |
| Même chose par le lanceur | `python3 scripts/dev/dev.py tableau-de-bord` ou `make tableau-de-bord` | `py -3 scripts/dev/dev.py tableau-de-bord` |
| Tests de l'outil (sans réseau) | `python3 -m unittest discover -s scripts/github -p "test_tableau_de_bord.py"` | `py -3 -m unittest discover -s scripts/github -p "test_tableau_de_bord.py"` |

**Aucun jeton n'est nécessaire** : le dépôt est public (60 appels par heure ; la commande en fait 5). Si la limite est atteinte, l'outil le dit et l'indicateur concerné est « non mesuré » ; définir `GITHUB_TOKEN` (jamais dans un fichier du dépôt) relève la limite. Le jeton part dans un en-tête, jamais dans l'adresse ni dans un message d'erreur.

Code de sortie : **0** si toutes les sources ont répondu, **1** si l'une d'elles est en défaut (la section « Sources en défaut » de la sortie la nomme).

## 4. Mesures

Ce bloc est **écrit par l'outil** (`--ecrire`), à partir de GitHub. Ne pas le modifier à la main : le prochain recalcul l'écraserait.

<!-- debut:mesures -->
Mesures du **2026-11-20 07:08 UTC**, dépôt `RobelManoa/novaria-core`, fichiers lus à : **main**.

| Indicateur | Valeur | Ce que dit un zéro |
|---|---|---|
| Exigences vérifiées (état « Prouvé ») | 23 sur 53 (43,4 %) | 0 prouvée : aucune exigence n'a sa preuve exécutée |
| Risques traités (statut « Clos ») | 0 sur 12 (0,0 %) | 0 clos : aucun risque n'a disparu ; ce n'est pas l'absence de risque |
| Livrables : issues fermées, tous jalons | 100 sur 125 (80,0 %) | 0 fermée : rien n'est livré |

### Exigences par état

| Priorité | Prouvé | Partiel | À faire |
|---|---|---|---|
| Doit | 19 | 16 | 3 |
| Devrait | 3 | 7 | 4 |
| Pourrait | 1 | 0 | 0 |
| **Toutes** | **23** | **23** | **7** |

### Risques par statut

| Ouvert | Suspendu | Clos |
|---|---|---|
| 11 | 1 | 0 |

### Livrables par jalon

| Jalon | Échéance | Fermées / total | Avancement | Preuves des issues fermées (versionnée / partielle / absente / non vérifiable) | P0 ouvertes |
|---|---|---|---|---|---|
| M0 · Cadrage et préparation | 2026-10-18 | 9 / 9 | 9 sur 9 (100,0 %) | 4 / 0 / 0 / 5 | 0 |
| M1 · Socle de livraison et spécifications | 2026-11-01 | 37 / 37 | 37 sur 37 (100,0 %) | 13 / 0 / 3 / 21 | 0 |
| M2 · Données et back-end | 2026-11-15 | 21 / 21 | 21 sur 21 (100,0 %) | 10 / 0 / 4 / 7 | 0 |
| M3 · Front-end | 2026-11-22 | 11 / 11 | 11 sur 11 (100,0 %) | 1 / 0 / 1 / 9 | 0 |
| M4 · IA, prototypes et intégration | 2026-11-29 | 20 / 23 | 20 sur 23 (87,0 %) | 15 / 0 / 1 / 4 | #92 |
| M5 · Stabilisation et documentation | 2026-12-06 | 2 / 10 | 2 sur 10 (20,0 %) | 1 / 0 / 1 / 0 | #95, #96, #99, #101, #102 |
| M6 · Intégration de la partie citoyen | 2026-12-08 | 0 / 8 | 0 sur 8 (0,0 %) | non mesuré (aucune issue fermée) | #269, #270, #271, #272, #274, #275 |
| M7 · Soutenance | 2026-12-10 | 0 / 6 | 0 sur 6 (0,0 %) | non mesuré (aucune issue fermée) | #103, #104, #105, #277, #278, #279 |

Issues sans jalon : 0.

### Preuves citées par une issue fermée et introuvables à cette révision

| Issue | Jalon | Chemin cité |
|---|---|---|
| #39 [BE-01] Écrire le contrat OpenAPI v1 (source de vérité) | M1 | `docs/02-specifications/openapi.yaml` |
| #51 [CLD-08] Preuve : un test en échec bloque la fusion | M1 | `docs/04-devsecops/preuves.md` |
| #56 [GES-08] Construire le planning dans ProjectLibre : WBS, dép | M1 | `planning/novaria-core.pod` |
| #62 [BE-02] Modèle métier SQLAlchemy et migrations Alembic | M2 | `backend/migrations/` |
| #63 [BE-03] Authentification JWT et rôles | M2 | `contract/` |
| #64 [BE-04] Endpoints des indicateurs lus depuis l'entrepôt | M2 | `contract/` |
| #66 [BE-06] Gestion des erreurs, validation et versionnement de  | M2 | `contract/` |
| #84 [DAT-09] Prototype flux temps réel : Kafka local et Flink (A | M4 | `docs/03-donnees/prototype-flux.md` |
| #93 [GES-09] Chiffrage AWS : inventaire réel, coûts et recommand | M5 | `docs/07-gestion/couts-aws.md` |
| #152 [LOC-05] Équivalents locaux des services AWS : port de stock | M3 | `backend/tests/` |
<!-- fin:mesures -->

## 5. Absence de mesure et résultat nul

Un indicateur peut valoir **zéro** (on a compté, il y en a zéro) ou **ne pas exister** (on n'a pas pu compter). Les deux ne se confondent jamais, ni dans le calcul ni à l'affichage.

| Situation | Affichage | Pourquoi |
|---|---|---|
| Aucun risque clos sur 12 risques lus | `0 sur 12 (0,0 %)` | Zéro est **le résultat** : on a lu 12 risques, aucun n'est clos. Cela ne dit pas « il n'y a aucun risque » |
| Un jalon n'a aucune issue | **non mesuré** (aucune issue dans ce jalon) | Un pourcentage sur zéro issue n'existe pas ; afficher 0 % laisserait croire à un retard |
| Aucune issue fermée dans un jalon | preuves : **non mesuré** (aucune issue fermée) | Il n'y a rien à compter : ce n'est pas « 0 preuve » |
| Une source répond en erreur (limite d'appels, réseau, fichier absent) | **non mesuré** et la raison (`HTTP 403`, `injoignable`) | Afficher 0 ferait passer une panne pour un résultat |
| Une ligne a un état ou un statut illisible | listée, ni comptée ni au dénominateur | Elle ne gonfle ni le haut ni le bas du ratio |
| Une preuve n'est pas un fichier (« sortie du plan », « capture ») | classée **non vérifiable** | Ce n'est ni présent ni absent : l'outil ne sait pas le dire |
| L'arbre des fichiers est illisible ou tronqué | preuves **non mesurées** | Aucune preuve n'est déclarée « absente » sans avoir vu l'arbre |

Tests : `test_tableau_de_bord.py`, classes `Exigences`, `Risques`, `Livrables`, `Calcul` et `Presentation` (chaque ligne du tableau ci-dessus y a son test).

## 6. Recalculer à la main, sans l'outil

Pour contrôler l'outil, chaque indicateur se retrouve avec des commandes de GitHub seules.

| Indicateur | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Issues fermées et total par jalon | `gh issue list --state all --limit 500 --json milestone,state --jq 'group_by(.milestone.title)\|map({jalon:.[0].milestone.title,total:length,fermees:(map(select(.state=="CLOSED"))\|length)})\|.[]'` | idem, en une ligne (les guillemets internes se protègent avec `\"`) |
| Exigences au total | `curl -s https://raw.githubusercontent.com/RobelManoa/novaria-core/main/docs/02-specifications/exigences.md \| grep -c "^\| EXG-"` | `((Invoke-WebRequest -UseBasicParsing <adresse>).Content -split "`n" \| Select-String '^\| EXG-').Count` |
| Exigences prouvées | même adresse, `grep -c "^\| EXG-.*\| Prouvé"` | même adresse, motif `'^\| EXG-.*\| Prouvé'` |
| Risques au total, risques clos | même principe sur `docs/07-gestion/registre-risques.md` : `grep -c "^\| R[0-9]* \|"` puis `grep -E "^\| R[0-9]+ \|" \| grep -c "\| Clos"` | `Select-String` avec les mêmes motifs |

Le bilan chiffré de `exigences.md` (« Prouvé / Partiel / À faire ») est déjà contrôlé par `scripts/dev/test_specifications.py` ; `test_tableau_de_bord.py` vérifie que l'outil retrouve les mêmes nombres.

## 7. Limites

| Limite | Conséquence |
|---|---|
| Une issue fermée n'est pas une preuve : l'indicateur « livrables » dit que le travail est **déclaré** fini, et ne juge pas sa qualité | La colonne « preuves » ajoute un contrôle d'existence du fichier cité, pas de son contenu |
| Beaucoup de preuves attendues ne sont pas des fichiers (captures, sorties de commande) | Elles sont **non vérifiables** par l'outil ; le total de la colonne dit combien |
| Un chemin cité dans une issue peut avoir changé de nom depuis (le dépôt a été réorganisé) | La liste « Preuves citées … introuvables » est un **signal à examiner**, pas un défaut démontré : corriger l'issue ou le document |
| Les fichiers lus à `main` ne contiennent pas le travail encore sur d'autres branches | Utiliser `--ref` ou `--local` pour voir l'état d'une branche |
| Le calcul lit le **format actuel** des deux tableaux | Un changement de colonnes fait échouer `test_tableau_de_bord.py` (classe `DocumentsDuDepot`) au lieu de donner un faux chiffre |
| Vérifié sous Linux ; non vérifié sous Windows | À rejouer par le binôme |
