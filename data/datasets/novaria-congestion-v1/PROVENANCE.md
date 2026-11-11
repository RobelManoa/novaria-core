# Fiche de provenance du jeu `novaria-congestion-v1` (version 1)

Issue : IA-08 · Décision : [ADR-027](../../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md), règles 1 à 8 · Fichier généré par `python3 ml/src/construire_jeu.py` : ne pas l'écrire à la main.

Abréviations : IA (intelligence artificielle), SHA-256 (Secure Hash Algorithm, empreinte de 256 bits), UTC (Temps universel coordonné).

> **Donnée simulée.** Tout ce jeu vient du simulateur du dépôt. Il ne décrit aucun trafic réel et ne doit jamais être présenté comme tel. Un modèle entraîné sur le simulateur apprend le simulateur : le résultat prouve la chaîne de bout en bout, pas la précision en conditions réelles.

## 1. Identifiant et version

| Rubrique | Valeur |
|---|---|
| `dataset_id` | `novaria-congestion-v1` |
| Version | 1 |
| Type de source (`source_type`) | `SIMULATED` |
| Lignes | 80 640 (une ligne par tronçon et par minute) |
| Colonnes | 36 (dictionnaire de données, section 9) |
| Empreinte du jeu | `5fc6f1832bd9f02dcf86de0e56dfbafb0854b57041819e6452820325c195c19e` (section 9 de cette fiche) |

## 2. Origine

| Rubrique | Valeur |
|---|---|
| Générateur | `simulator/novaria_sim` version 1.0.0 (issue MS-07) |
| Constructeur du jeu | `ml/src/jeu_entrainement`, version 1.0.0 |
| Agrégation en fenêtres | `services/traitement/app/flux/windows.py` : le moteur du traitement en flux, rejoué sur les messages de chaque run, dans l'ordre de livraison |
| Vérité terrain | l'état de congestion **voulu par le scénario** (`verite-terrain` du simulateur), pas la règle de seuils de l'ADR-028 |
| Graines | 11, 12, 13, 14, 21, 22, 23, 24, 31, 32, 33, 34 (une par run, toutes différentes) |
| Format | Parquet, colonnes PLAIN, sans compression, écrit par ml/src/jeu_entrainement/parquet.py |

Le jeu se **régénère** par sa graine : le dépôt garde le catalogue (`ml/src/jeu_entrainement/catalogue.py`), cette fiche et le manifeste, pas les fichiers Parquet ([ADR-027](../../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md), règle 6).

## 3. Licence et conditions

| Rubrique | Valeur |
|---|---|
| Données | synthétiques, produites par le code du dépôt : aucune donnée de tiers, aucune licence de données à respecter |
| Redistribution | possible, puisque le jeu se régénère ; **la licence du dépôt n'est pas encore fixée** (aucun fichier `LICENSE`) : à décider avant toute publication |
| Données personnelles | aucune |

## 4. Période et couverture

| Scénario | Runs | Plage horaire (UTC, 20/10/2026) | Durée | Ce que le scénario impose |
|---|---|---|---|---|
| journée calme (`journee-calme`) | 4 | 08:00 à 14:00 | 6 h | tous les tronçons restent fluides |
| heure de pointe (`heure-de-pointe`) | 4 | 06:00 à 11:00 | 5 h | les approches Nord et Ouest se saturent de 07:20 à 08:50, décalage de 0 à 12 minutes par tronçon |
| incident ponctuel (`incident-ponctuel`) | 4 | 07:30 à 10:30 | 3 h | incident sur ROAD_005 de 08:10 à 08:35, les autres approches du carrefour INT_02 ralentissent |

Réseau fixe du simulateur : 6 carrefours, **24 tronçons d'approche**, un capteur par tronçon, une mesure toutes les 10 secondes. Pas de temps du jeu : **1 minute** (6 mesures attendues par fenêtre). Un seul jour simulé : le 20/10/2026.

### Catalogue des runs

Les trois scénarios sont combinés avec les trois anomalies de l'ADR-027 (règle 8), injectées sur un capteur à la fois :

| Anomalie injectée | Runs |
|---|---|
| `doublon` | `ds1-calme-s14`, `ds1-pointe-s22`, `ds1-incident-s33` |
| `muet` | `ds1-calme-s12`, `ds1-pointe-s23`, `ds1-pointe-s24`, `ds1-incident-s32` |
| `retard` | `ds1-calme-s13`, `ds1-pointe-s22`, `ds1-pointe-s24`, `ds1-incident-s34` |

| Run | Scénario | Graine | Ensemble | Anomalies | Lignes |
|---|---|---|---|---|---|
| `ds1-calme-s11` | journée calme | 11 | entraînement | sans anomalie | 8 640 |
| `ds1-calme-s12` | journée calme | 12 | entraînement | capteur muet pendant 10 minutes | 8 640 |
| `ds1-calme-s13` | journée calme | 13 | validation | messages en retard de 2 minutes (refusés par le traitement) | 8 640 |
| `ds1-calme-s14` | journée calme | 14 | test | messages reçus trois fois | 8 640 |
| `ds1-pointe-s21` | heure de pointe | 21 | entraînement | sans anomalie | 7 200 |
| `ds1-pointe-s22` | heure de pointe | 22 | entraînement | retards et doublons pendant la montée | 7 200 |
| `ds1-pointe-s23` | heure de pointe | 23 | validation | capteur muet pendant la saturation | 7 200 |
| `ds1-pointe-s24` | heure de pointe | 24 | test | retards puis capteur muet | 7 200 |
| `ds1-incident-s31` | incident ponctuel | 31 | entraînement | sans anomalie | 4 320 |
| `ds1-incident-s32` | incident ponctuel | 32 | entraînement | le capteur de l'incident se tait pendant l'incident | 4 320 |
| `ds1-incident-s33` | incident ponctuel | 33 | validation | messages reçus trois fois | 4 320 |
| `ds1-incident-s34` | incident ponctuel | 34 | test | messages en retard de 2 minutes (refusés par le traitement) | 4 320 |

## 5. Variables et unités

Les colonnes et leurs définitions sont celles du [dictionnaire de données](../../../docs/03-donnees/dictionnaire-de-donnees.md), section 9 ; les mesures ont les définitions de la section 6 (même moteur de calcul, mêmes arrondis que l'entrepôt).

| Groupe | Colonnes |
|---|---|
| clé | `run_id`, `scenario_id`, `seed`, `road_segment_id`, `window_start` |
| mesures | `vehicle_count`, `flow_veh_per_min`, `average_speed_kmh`, `occupancy_rate`, `max_queue_length_m`, `speed_ratio` |
| historique | `speed_ratio_lag1`, `speed_ratio_lag2`, `speed_ratio_lag3`, `speed_ratio_lag4`, `speed_ratio_lag5`, `flow_lag1`, `flow_lag2`, `flow_lag3`, `flow_lag4`, `flow_lag5`, `speed_ratio_ma5`, `speed_ratio_ma15`, `flow_ma5`, `flow_ma15` |
| calendrier | `hour_of_day`, `iso_day_of_week`, `is_weekend`, `is_holiday` |
| tronçon | `lane_count`, `length_m`, `free_flow_speed_kmh`, `road_type` |
| réponses | `label_state`, `speed_ratio_h5`, `speed_ratio_h15` |

Notes :
- `window_start` : début de la fenêtre, UTC, en microsecondes ; `flow_veh_per_min` : véhicules par minute ; `average_speed_kmh` : km/h ; `occupancy_rate` : de 0 à 1 ; `max_queue_length_m` : mètres ; `speed_ratio` : vitesse moyenne divisée par la vitesse fluide (0 à 9,999).
- Une valeur qui n'existe pas est **absente** (`null`) : route vide, début ou fin de run, historique pas encore disponible. Rien n'est inventé.
- `speed_ratio_lag1` à `lag5` et `flow_lag1` à `lag5` : la valeur des 1 à 5 minutes **précédentes** du même tronçon. `speed_ratio_ma5`, `speed_ratio_ma15`, `flow_ma5`, `flow_ma15` : moyenne des valeurs présentes des 5 ou 15 minutes précédentes. Aucune ne regarde la ligne elle-même ni l'avenir.
- `speed_ratio_h5` et `speed_ratio_h15` : le `speed_ratio` du même tronçon 5 et 15 minutes plus tard (réponses de la prévision).
- `label_state` : `FREE_FLOW`, `SLOW` ou `CONGESTED`, l'état voulu par le scénario pour cette minute (l'état le plus fréquent de ses 6 intervalles ; à égalité, le dernier).

## 6. Découpage : par run et par scénario

| Ensemble | Fichier | Runs | Lignes | `FREE_FLOW` | `SLOW` | `CONGESTED` |
|---|---|---|---|---|---|---|
| entraînement | `train.parquet` | 6 | 40 320 | 88,9 % | 7,4 % | 3,7 % |
| validation | `validation.parquet` | 3 | 20 160 | 88,9 % | 7,4 % | 3,7 % |
| test | `test.parquet` | 3 | 20 160 | 88,9 % | 7,4 % | 3,7 % |

| Règle | Garantie |
|---|---|
| Par run | un `run_id` appartient à **un seul** ensemble ; une graine aussi (vérifié par `ml/tests/test_catalogue.py` et sur les fichiers écrits par `ml/tests/test_construire.py`) |
| Par scénario | chaque ensemble contient des runs de **chacun** des trois scénarios |
| Jamais par lignes | des minutes voisines d'un même run se ressemblent : un tirage au hasard ferait fuir le test vers l'entraînement |

Les parts d'états sont presque identiques d'un ensemble à l'autre : les runs d'un même scénario ont le même calendrier d'états (section 8), et chaque ensemble a les mêmes scénarios dans les mêmes proportions.

## 7. Qualité mesurée

| Run | Lignes | Fenêtres vides | Fenêtres incomplètes | Minutes à états mélangés | Messages livrés | Doublons écartés | Refusés (en retard) | Intervalles muets |
|---|---|---|---|---|---|---|---|---|
| `ds1-calme-s11` | 8 640 | 0 | 0 | 0 | 51 840 | 0 | 0 | 0 |
| `ds1-calme-s12` | 8 640 | 9 | 2 | 0 | 51 780 | 0 | 0 | 60 |
| `ds1-calme-s13` | 8 640 | 19 | 2 | 0 | 51 840 | 0 | 120 | 0 |
| `ds1-calme-s14` | 8 640 | 0 | 0 | 0 | 52 200 | 360 | 0 | 0 |
| `ds1-pointe-s21` | 7 200 | 0 | 0 | 56 | 43 200 | 0 | 0 | 0 |
| `ds1-pointe-s22` | 7 200 | 29 | 2 | 56 | 43 380 | 180 | 180 | 0 |
| `ds1-pointe-s23` | 7 200 | 14 | 2 | 56 | 43 110 | 0 | 0 | 90 |
| `ds1-pointe-s24` | 7 200 | 28 | 4 | 56 | 43 140 | 0 | 120 | 60 |
| `ds1-incident-s31` | 4 320 | 0 | 0 | 9 | 25 920 | 0 | 0 | 0 |
| `ds1-incident-s32` | 4 320 | 19 | 2 | 9 | 25 800 | 0 | 0 | 120 |
| `ds1-incident-s33` | 4 320 | 0 | 0 | 9 | 26 160 | 240 | 0 | 0 |
| `ds1-incident-s34` | 4 320 | 19 | 2 | 9 | 25 920 | 0 | 120 | 0 |

Lecture : une **fenêtre vide** n'a reçu aucune mesure (capteur muet) ; une **fenêtre incomplète** en a reçu moins de 6 ; une **minute à états mélangés** contient des intervalles d'états voulus différents (le changement d'état tombe dans la minute). Un **doublon écarté** est une copie d'un message déjà reçu ; un message **refusé en retard** arrive après la fermeture de sa fenêtre (règle DQ-04 du traitement en flux) et n'entre pas dans le jeu.

Valeurs absentes (part des lignes) :

| Ensemble | `average_speed_kmh` | `speed_ratio` | `speed_ratio_lag5` | `speed_ratio_h15` |
|---|---|---|---|---|
| entraînement | 3,9 % | 3,9 % | 5,6 % | 9,1 % |
| validation | 3,8 % | 3,8 % | 5,5 % | 9,1 % |
| test | 3,8 % | 3,8 % | 5,5 % | 9,0 % |

## 8. Limites

| Limite | Conséquence |
|---|---|
| Données simulées | un bon résultat prouve la chaîne, pas la précision réelle (ADR-027) |
| La graine ne change que le bruit, pas le calendrier des états | deux runs d'un même scénario ont la même suite d'états voulus : le test mesure la généralisation à un **autre bruit**, pas à un **scénario jamais vu**. Évaluer sur une situation nouvelle demande un quatrième scénario dans le simulateur |
| Un seul jour, un seul réseau de 24 tronçons | `iso_day_of_week`, `is_weekend` et `is_holiday` ne varient pas : ces colonnes ne portent aucune information dans la version 1 |
| `hour_of_day` suit le scénario | les plages horaires diffèrent d'un scénario à l'autre (section 4) : un modèle peut deviner le scénario par l'heure |
| Classes déséquilibrées | `CONGESTED` est rare (section 6) ; l'exactitude seule est trompeuse, utiliser le rappel et la précision par classe |
| Un capteur muet donne une fenêtre vide | la colonne ne distingue pas une route sans véhicule d'un capteur silencieux (la complétude n'est pas dans les colonnes du dictionnaire) |
| Retards et doublons jugés comme en production | un message très en retard est refusé : le jeu n'en garde que l'effet (fenêtre incomplète) |
| Réponses de prévision absentes en fin de run | les 5 ou 15 dernières minutes de chaque run n'ont pas de `speed_ratio_h5` ou `h15` |
| Écrivain Parquet maison | le format est validé en relecture avec `pyarrow` (outil d'essai, pas une dépendance) ; non vérifié avec d'autres lecteurs |
| Windows et macOS | non vérifiés : l'empreinte a été relevée sous Linux ; elle doit être la même ailleurs (calculs décimaux et flottants IEEE, aucun fichier compressé) |

## 9. Empreinte

| Fichier | SHA-256 | Octets | Lignes |
|---|---|---|---|
| `test.parquet` | `3a8fc3073a8b0795b542a7bf220686a2689eaf8e9dcb7625f4df8b9a5d75ac6a` | 5 686 929 | 20 160 |
| `train.parquet` | `2499018d62ab37111049ec20e2072a54fee431911751393b19a0e14b00ed78c6` | 11 371 476 | 40 320 |
| `validation.parquet` | `68453e870964ee3272ed8949bc6f7afeb79b7c1b9ffec9f5213e887c2fb538fd` | 5 687 250 | 20 160 |

**Empreinte du jeu** : `5fc6f1832bd9f02dcf86de0e56dfbafb0854b57041819e6452820325c195c19e` = SHA-256 du texte « nom de fichier, espace, SHA-256 » (une ligne par fichier, triées par nom, fin de ligne LF).

La même empreinte est écrite dans `manifest.json`. L'enregistrement de l'empreinte dans MongoDB (`model_runs`, ADR-027 règle 5) se fait à l'entraînement d'un modèle (IA-04, IA-05) : un document par entraînement cite `dataset_id` et cette empreinte.

### Régénérer et vérifier

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Construire le jeu | `python3 ml/src/construire_jeu.py` | `py -3 ml/src/construire_jeu.py` |
| Comparer | `sha256sum data/datasets/novaria-congestion-v1/*.parquet` | `Get-FileHash data\datasets\novaria-congestion-v1\*.parquet` |
| Lancer les tests | `python3 -m unittest discover -s ml/tests -t ml` | `py -3 -m unittest discover -s ml\tests -t ml` |

Si un SHA-256 diffère de celui de la section ci-dessus, le jeu n'est pas celui de cette fiche : le code, le simulateur ou le catalogue a changé. Reconstruire, relire le diff de cette fiche, puis la commiter avec le code.
