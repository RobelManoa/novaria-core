# Prototype Big Data : PySpark en mode local (DAT-08)

Le nettoyage du comptage routier de Paris ([DAT-04](../../docs/03-donnees/nettoyage-paris.md)) refait avec PySpark, puis comparé à l'ETL Python. Prototype ciblé : il vit dans son dossier et son image, hors des quatre services ([ADR-016](../../docs/01-architecture/adr/ADR-016-big-data.md)). Amazon EMR (Elastic MapReduce) est **documenté, non exécuté** ([ADR-023](../../docs/01-architecture/adr/ADR-023-execution-locale-d-abord.md)).

**Rapport : [docs/03-donnees/prototype-bigdata.md](../../docs/03-donnees/prototype-bigdata.md)** (ce que le prototype démontre, ce qu'il ne démontre pas, mesures).

Les données sont **simulées** : même forme que l'export de Paris, défauts injectés en proportions connues. Aucune donnée réelle n'est redistribuée (licence ODbL).

## Contenu

| Fichier | Rôle |
|---|---|
| `Dockerfile`, `requirements.in`, `requirements.txt` | Image : Python 3.12, Java 21, PySpark 4.1.4 installé avec ses empreintes (`--require-hashes`) |
| `bigdata/generer.py` | Historique simulé, un fichier par jour au format du portail ; vérité terrain de chaque défaut injecté |
| `bigdata/nettoyage_python.py` | L'ETL de production (`pipelines.nettoyer_paris`) lancé en séquentiel ou réparti par fichier |
| `bigdata/nettoyage_spark.py` | Les sept règles de `transforms.paris_qualite` en colonnes PySpark |
| `bigdata/empreinte.py` | Empreinte des résultats (entiers, indépendante de l'ordre des lignes) pour comparer les deux moteurs |
| `bigdata/mesure.py` | Durée et pic de mémoire de chaque moteur, parité, rapport JSON |
| `tests/` | Tests Python seul (générateur, ETL, mesure) et tests PySpark (cas limites, divergences connues, bout en bout) |

## Lancer

Docker est la seule exigence. Le dépôt est monté en lecture seule ; les données vont dans le volume Docker `novaria-bigdata` (jamais dans le dossier du projet).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Construire l'image (la première fois : plusieurs minutes, 450 Mo à télécharger) | `python3 scripts/dev/dev.py bigdata-build` (ou `make bigdata-build`) | `py -3 scripts/dev/dev.py bigdata-build` |
| Tests du prototype (PySpark compris) | `python3 scripts/dev/dev.py bigdata-test` | `py -3 scripts/dev/dev.py bigdata-test` |
| Générer 90 jours (6,4 millions de lignes, 1,6 Go) | `python3 scripts/dev/dev.py bigdata -- generer --dossier /data/paris --jours 90` | `py -3 scripts/dev/dev.py bigdata -- generer --dossier /data/paris --jours 90` |
| Mesurer 7 et 30 jours, trois moteurs | `python3 scripts/dev/dev.py bigdata -- mesurer --dossier /data/paris --jours 7,30 --moteurs python-sequentiel,python-parallele:4,spark:4` | `py -3 scripts/dev/dev.py bigdata -- mesurer --dossier /data/paris --jours 7,30 --moteurs python-sequentiel,python-parallele:4,spark:4` |
| Un seul moteur, puis sa vérification | `python3 scripts/dev/dev.py bigdata -- nettoyer --moteur spark --coeurs 4 --jours 7` puis `python3 scripts/dev/dev.py bigdata -- verifier --moteur spark --coeurs 4 --jours 7` | `py -3 scripts/dev/dev.py bigdata -- nettoyer --moteur spark --coeurs 4 --jours 7` puis `py -3 scripts/dev/dev.py bigdata -- verifier --moteur spark --coeurs 4 --jours 7` |
| Supprimer les données | `docker volume rm novaria-bigdata` | `docker volume rm novaria-bigdata` |

Ressources par défaut : 4 cœurs et 6 Go (`--cpus`, `--memoire` de `dev.py bigdata`). Une mesure sans sa machine ne dit rien : le rapport de `mesurer` écrit l'environnement (versions, cœurs, limites).

Sous Windows avec Docker Desktop, le volume est dans la machine virtuelle de Docker ; le code est lu depuis le dossier du projet (montage en lecture seule). **Non vérifié sous Windows.**

## Ce que fait chaque moteur (même entrée, mêmes règles)

```mermaid
flowchart LR
    G[generer<br/>fichiers journaliers<br/>+ vérité terrain] --> D[(volume Docker<br/>/data/paris)]
    D --> P1[python-sequentiel<br/>pipelines.nettoyer_paris<br/>1 processus]
    D --> P2[python-parallele<br/>1 processus par fichier]
    D --> S[spark local[N]<br/>une partition par fichier]
    P1 & P2 --> E1[propre/*.csv · rejets/*.jsonl]
    S --> E2[Parquet<br/>statut=propre · statut=rejet]
    E1 & E2 --> V[verifier<br/>empreintes]
    V --> R[comparaison<br/>+ vérité terrain]
```
