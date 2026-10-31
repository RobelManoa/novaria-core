# Indicateurs décisionnels (KPI) : définition, source, calcul et limites

> Issue #61 (DAT-07). Critère : **chaque indicateur se recalcule à partir de la source annoncée**. Les vues sont dans
> [`data/dwh/sql/kpi/`](../../data/dwh/sql/kpi/) (migration `0006_kpi_vues.sql`) ; le contrôle de recalcul est
> [`controle/verifier.sql`](../../data/dwh/sql/kpi/controle/verifier.sql), lancé par `python3 scripts/dev/dev.py db-check-kpi`.
> Cadre : [ADR-014](../01-architecture/adr/ADR-014-architecture-decisionnelle.md) (section 4.2), [ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md)
> (états, épisodes, alertes), [dictionnaire de données](dictionnaire-de-donnees.md) (sections 6 et 7).

## 1. Principe

Un indicateur = une **définition écrite** (cette fiche), une **vue SQL** en lecture seule, un **recalcul indépendant** sur les
tables sources et une **limite connue**. L'API de consultation et le tableau de bord liront ces vues et rien d'autre
([ADR-014](../01-architecture/adr/ADR-014-architecture-decisionnelle.md), section 4.3) ; le compte `svc_lecture` les lit, sans pouvoir écrire dans les faits.

Règles communes à tous les indicateurs :

- **Jour et heure en UTC.** Un jour est un jour UTC, jamais local.
- **Provenance visible.** Chaque ligne porte `run_id` et `source_type` : un chiffre `SIMULATED` n'est jamais présenté comme une mesure
  ([ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md), EXG-NFR-13). Deux exécutions ne se mélangent pas.
- **Taille de fenêtre.** Les vues sur les fenêtres séparent les tailles (`window_size_s`) : l'état d'alerte vient des fenêtres de 1 minute,
  celles de 5 minutes servent aux tendances ; additionner les deux compterait le temps deux fois.
- **Un trou se voit.** Quand une valeur ne peut pas se calculer (rien observé, épisode en cours, observation absente), la vue rend `NULL`
  ou un compteur séparé, jamais zéro.

## 2. Vue d'ensemble

| # | Indicateur | Vue | Source | Décision qu'il éclaire |
|---|---|---|---|---|
| KPI-01 | Part du temps en état CONGESTED, par tronçon et par jour | `dwh.kpi_part_temps_congestionne` | `fact_traffic_window` | Quels tronçons ajuster en priorité |
| KPI-02 | Durée moyenne des épisodes, par tronçon | `dwh.kpi_duree_episodes` | `fact_congestion_episode` | Une congestion est-elle brève (absorbable) ou durable (à traiter) |
| KPI-03 | Délai de détection d'une congestion | `dwh.kpi_delai_detection` | `alertes.alert`, `fact_congestion_episode`, `fact_traffic_window` | Régler les seuils et l'hystérésis (ADR-028) |
| KPI-04 | Alertes par jour et par type | `dwh.kpi_alertes_par_jour` | `alertes.alert` | Charge d'alertes subie par les usagers et les opérateurs |
| KPI-05 | Vitesse relative par tronçon et par heure | `dwh.kpi_vitesse_relative_horaire` | `fact_traffic_window` | Quand, dans la journée, un tronçon se dégrade |

Les quatre premiers sont les indicateurs de congestion demandés par l'issue ; le cinquième est l'indicateur de circulation de l'ADR-014
(« vitesse par rapport à la référence ») dans sa forme la plus simple.

## 3. Fiches

### KPI-01 · Part du temps en état CONGESTED

| | |
|---|---|
| **Définition** | Fraction du temps observé pendant laquelle l'état stabilisé d'un tronçon était CONGESTED |
| **Source** | `dwh.fact_traffic_window` : `congestion_state` (état stabilisé par l'hystérésis, pas le classement brut de la fenêtre), `window_size_s` |
| **Calcul** | `congestionne_s ÷ observe_s`, où `congestionne_s` = somme de `window_size_s` des fenêtres CONGESTED et `observe_s` = somme de `window_size_s` des fenêtres dont l'état n'est pas UNKNOWN. Arrondi à 4 décimales |
| **Grain** | `run_id`, `source_type`, tronçon, jour UTC, taille de fenêtre |
| **Colonnes** | `congestionne_s`, `observe_s`, `inconnu_s`, `part_congestionne` (`NULL` si `observe_s` = 0) |
| **Décision** | Classer les tronçons par part de congestion pour décider où ajuster les plans de feux en premier |
| **Limites** | (1) Le seuil de congestion est une valeur de départ de l'ADR-028 (ratio < 0,35 pendant 2 fenêtres) : la part change si le seuil change. (2) Les fenêtres UNKNOWN sortent du dénominateur : un tronçon aveugle la moitié du jour affiche une part calculée sur l'autre moitié, d'où `inconnu_s` à lire avec elle. (3) Une fenêtre sans véhicule compte comme fluide (ADR-028). (4) Sur le réseau de démonstration, le chiffre dépend du scénario du générateur, pas de la réalité |

### KPI-02 · Durée moyenne des épisodes

| | |
|---|---|
| **Définition** | Durée moyenne des épisodes de dégradation clos : de l'ouverture (l'état quitte FREE_FLOW) au retour à FREE_FLOW |
| **Source** | `dwh.fact_congestion_episode` : `started_at`, `ended_at`, `peak_state` |
| **Calcul** | Moyenne de `ended_at − started_at` en secondes sur les épisodes où `ended_at` est renseigné ; arrondi à 0,1 s. Les épisodes en cours (`ended_at` nul) sont comptés dans `episodes_en_cours`, jamais dans la moyenne |
| **Grain** | `run_id`, `source_type`, tronçon, jour UTC de `started_at`, `peak_state` |
| **Colonnes** | `episodes_clos`, `episodes_en_cours`, `duree_moyenne_s`, `duree_max_s` |
| **Décision** | Distinguer les congestions brèves, que l'usager absorbe, des durables, qui justifient un changement de plan. Les épisodes de **congestion** sont ceux dont `peak_state` vaut CONGESTED ; ceux de `peak_state` SLOW sont des ralentissements |
| **Limites** | (1) Un épisode qui franchit minuit compte pour le jour où il commence. (2) Exclure les épisodes en cours **sous-estime** la durée tant que les plus longs ne sont pas finis : lire `episodes_en_cours` avec la moyenne. (3) L'épisode s'ouvre dès SLOW : sa durée inclut le ralentissement qui précède la congestion. (4) Peu d'épisodes par jour et par tronçon : une moyenne sur un ou deux épisodes ne vaut pas tendance |

### KPI-03 · Délai de détection

| | |
|---|---|
| **Définition** | Temps écoulé entre la première observation de congestion d'un épisode et l'ouverture de l'alerte correspondante |
| **Sources** | `alertes.alert` (`kind` = CONGESTION, `opened_at`, `episode_id`) ; `dwh.fact_congestion_episode` (lien par `episode_id`, sans clé étrangère entre services : [ADR-008](../01-architecture/adr/ADR-008-microservices.md)) ; `dwh.fact_traffic_window` (`speed_ratio`) |
| **Calcul** | `opened_at` − début de la **première fenêtre de l'épisode dont le `speed_ratio` est inférieur à 0,35** (seuil de montée vers CONGESTED de l'ADR-028). Moyenne, médiane et maximum en secondes, arrondis à 0,1 s |
| **Grain** | `run_id`, `source_type`, jour UTC de `opened_at` |
| **Colonnes** | `alertes`, `alertes_mesurees`, `delai_moyen_s`, `delai_median_s`, `delai_max_s` |
| **Décision** | Régler l'hystérésis et les seuils : trop de retard, on ose des seuils plus sensibles ; trop d'alertes ([KPI-04](#kpi-04--alertes-par-jour-et-par-type)), on les durcit. L'ADR-028 annonce 2 à 3 minutes |
| **Limites** | (1) C'est un délai **de la chaîne**, observation brute → alerte : il contient les 2 fenêtres de confirmation et la latence du traitement. Le délai **réel** (par rapport au début de la congestion simulée) demande la vérité terrain du générateur, qui n'est pas dans l'entrepôt : il se mesure en IA-03. (2) Le seuil 0,35 est écrit dans la vue ; s'il change dans le classificateur, il doit changer ici. (3) Une alerte sans épisode, ou sans fenêtre sous le seuil, ou ouverte avant l'observation, est comptée dans `alertes` mais pas dans `alertes_mesurees` : l'écart entre les deux est un défaut de données à regarder, pas un détail. (4) Fenêtres de 1 ou de 5 minutes : à 5 minutes, le délai ne peut pas descendre sous la fenêtre |

### KPI-04 · Alertes par jour et par type

| | |
|---|---|
| **Définition** | Nombre d'alertes ouvertes un jour donné, par type, avec leur état de résolution |
| **Source** | `alertes.alert` : `opened_at`, `kind`, `state` |
| **Calcul** | `count(*)` par (`run_id`, `source_type`, jour UTC de `opened_at`, `kind`) ; `resolues` = état RESOLVED, `non_resolues` = les autres |
| **Colonnes** | `alertes`, `resolues`, `non_resolues` |
| **Décision** | Mesurer la charge d'alertes. Une alerte par épisode (ADR-028) : un nombre qui explose signale un seuil trop sensible ou un réseau réellement dégradé |
| **Limites** | (1) Compter les alertes ne dit pas combien étaient **justifiées** : les fausses alertes demandent la vérité terrain du générateur (IA-03). (2) Les alertes d'un jour comptent à leur ouverture, même résolues le lendemain. (3) Une alerte `SENSOR_FAULT` n'est pas une congestion : lire par `kind`. (4) Sans alerte ce jour-là, la vue n'a pas de ligne : l'absence de ligne vaut zéro, à traduire dans l'affichage |

### KPI-05 · Vitesse relative par heure

| | |
|---|---|
| **Définition** | Vitesse moyenne rapportée à la vitesse en circulation fluide du tronçon (1 = fluide), par heure de la journée |
| **Source** | `dwh.fact_traffic_window` : `speed_ratio`, `vehicle_count` |
| **Calcul** | `Σ(speed_ratio × vehicle_count) ÷ Σ(vehicle_count)` sur les fenêtres qui ont un ratio ; arrondi à 3 décimales |
| **Grain** | `run_id`, `source_type`, tronçon, jour UTC, heure UTC, taille de fenêtre |
| **Colonnes** | `fenetres`, `fenetres_avec_vitesse`, `vehicules`, `vitesse_relative` |
| **Décision** | Voir à quelles heures un tronçon se dégrade, pour caler les plans de feux sur les heures de pointe |
| **Limites** | (1) La pondération par les véhicules donne peu de poids aux fenêtres creuses : la nuit, quelques véhicules suffisent à fixer le chiffre. (2) Une fenêtre sans véhicule n'a pas de ratio : elle n'entre pas dans la moyenne (une route vide n'est pas une route arrêtée). (3) La vitesse fluide du réseau de démonstration est égale à la vitesse limite (hypothèse de simulation) : le ratio ne dépasse guère 1. (4) L'ADR-014 parlait d'une référence **horaire** calculée sur plusieurs jours : ce n'est pas fait, faute de jours de données ; la référence est ici la vitesse fluide |

## 4. Recalcul à partir de la source

`controle/verifier.sql` ne touche pas aux données du projet : il insère un jeu fabriqué (exécution `kpi-controle`, source
`SIMULATED`) **dans une transaction qu'il annule**, puis compare, pour 39 grandeurs, trois valeurs :

| Valeur | Origine |
|---|---|
| **vue** | ce que renvoie la vue `dwh.kpi_*` |
| **recalcul** | la même grandeur recalculée **sans la vue**, directement sur les tables sources, avec une autre écriture (comptage de fenêtres × 60 s au lieu d'une somme de `window_size_s` ; jointure latérale et médiane lue dans un tableau trié au lieu de `percentile_cont` ; etc.) |
| **attendu** | le résultat calculé à la main ci-dessous |

Un écart lève une exception : la commande rend un code d'erreur.

### Jeu de contrôle et calculs à la main

Fenêtres de 1 minute le 2026-10-30, vitesse fluide 50 km/h ; ratio brut et état stabilisé.

- **ROAD_001** : 10:00 à 10:09 → (20, 0,90, FLUIDE) (20, 0,80, FLUIDE) (18, 0,50, SLOW) (16, 0,40, SLOW) (14, 0,30, SLOW) (12, 0,30, CONGESTED)
  (10, 0,20, CONGESTED) (10, 0,30, CONGESTED) (14, 0,50, SLOW) (20, 0,90, FLUIDE) ; 10:10 (0 véhicule) et 10:11 (6 véhicules, sans vitesse) en UNKNOWN ;
  10:20 à 10:23 : 4 fenêtres (10, 0,50, SLOW).
- **ROAD_002** : 10:29 (20, 0,90, FLUIDE) ; 10:30 à 10:34 : 5 fenêtres (8, 0,30, CONGESTED).
- **Épisodes** : E1 ROAD_001 10:02 → 10:09 (CONGESTED) ; E2 ROAD_001 10:20 → 10:24 (SLOW) ; E3 ROAD_002 depuis 10:30, en cours (CONGESTED) ; E4 ROAD_001 11:00 → 11:03 (CONGESTED), sans fenêtre chargée.
- **Alertes** : A1 sur E1, ouverte 10:06:10, résolue ; A2 sur E3, ouverte 10:33:00 ; A4 sur E4, ouverte 11:02:00 ; A3 `SENSOR_FAULT` le 31/10 à 08:00.

| Indicateur | Calcul à la main | Valeur |
|---|---|---|
| KPI-01 ROAD_001 | 3 fenêtres CONGESTED = 180 s ; fenêtres connues : 10 + 4 = 14 = 840 s ; UNKNOWN : 2 = 120 s ; 180 ÷ 840 | **0,2143** |
| KPI-01 ROAD_002 | 5 × 60 = 300 s CONGESTED ; connues : 6 = 360 s ; 300 ÷ 360 | **0,8333** |
| KPI-02 ROAD_001 CONGESTED | E1 = 420 s, E4 = 180 s ; (420 + 180) ÷ 2 ; maximum 420 | **300,0** s |
| KPI-02 ROAD_001 SLOW | E2 = 240 s | **240,0** s |
| KPI-02 ROAD_002 CONGESTED | E3 en cours : 0 épisode clos, 1 en cours | durée **NULL** |
| KPI-03 | A1 : première fenêtre sous 0,35 de E1 = 10:04:00, alerte 10:06:10, soit 130 s. A2 : 10:30:00 → 10:33:00, soit 180 s. A4 : aucune fenêtre chargée, non mesurable | 3 alertes, 2 mesurées, moyenne **155,0** s, médiane **155,0** s, maximum **180,0** s |
| KPI-04 30/10 CONGESTION | A1, A2, A4 ; A1 résolue | 3 alertes, 1 résolue, 2 non résolues |
| KPI-04 31/10 SENSOR_FAULT | A3 | 1 alerte, 0 résolue, 1 non résolue |
| KPI-05 ROAD_001, 10 h | Σ ratio × véhicules = 87,2 + 20 = 107,2 ; véhicules avec ratio : 154 + 40 = 194 ; 107,2 ÷ 194 = 0,5526 ; (véhicules totaux : 200, dont 6 sans ratio, hors dénominateur) | **0,553** |
| KPI-05 ROAD_002, 10 h | 18 + 5 × 8 × 0,3 = 30 ; véhicules : 20 + 40 = 60 ; 30 ÷ 60 | **0,500** |

Les valeurs choisies rendent chaque défaut visible : une fenêtre UNKNOWN **avec** véhicules (pour que le dénominateur de KPI-05 ne les compte pas), un
épisode en cours (pour qu'il n'entre pas dans la moyenne de KPI-02), une alerte sans fenêtre (pour que KPI-03 la compte sans la mesurer), un jour sans
alerte de congestion (KPI-04) et une médiane de deux valeurs (KPI-03).

### Résultat (30/10/2026, PostgreSQL 16 sous Docker, poste Windows)

```text
NOTICE:  KPI : 39 comparaisons, aucun écart entre la vue, le recalcul sur les sources et la valeur attendue
```

Les 39 lignes sont `OK`. Aucune ligne ne reste en base après le contrôle (transaction annulée, vérifié). Le compte `svc_lecture` lit les cinq vues et se voit refuser une
écriture dans `fact_traffic_window`.

**Le contrôle détecte des défauts.** 12 modifications volontaires des vues (mauvais dénominateur, SLOW compté comme CONGESTED, épisodes en cours comptés comme clos, moyenne remplacée par un maximum,
seuil de détection changé, fenêtre d'épisode élargie, alertes non mesurées comptées comme mesurées, médiane remplacée par un percentile 0,9, résolues mal comptées,
non résolues mal comptées, pondération par les véhicules remplacée par une moyenne simple, véhicules sans ratio laissés dans le dénominateur) ont toutes fait échouer la
commande ; la dernière n'était d'abord pas détectée, ce qui a fait ajouter la fenêtre UNKNOWN avec véhicules. Le test `scripts/dev/test_kpi.py` (fiche, migration,
contrôle) a lui aussi été éprouvé : 11 défauts introduits dans les vues, la migration, la fiche, le contrôle et `dev.py`, tous détectés. Une treizième modification ne changeait rien au résultat (`0 + x`) et deux autres n'étaient
pas applicables : elles ne comptent pas.

## 5. Écarts avec l'ADR-014, section 4.2

| Proposé par l'ADR-014 | Décision de DAT-07 | Raison |
|---|---|---|
| Minutes de congestion par carrefour et par jour | Remplacé par KPI-01 (part du temps, par **tronçon**) | Le tronçon est l'unité d'analyse (EXG-TRA-01) ; le carrefour s'obtient en regroupant par `dim_road_segment.intersection_key` |
| Vitesse moyenne par rapport à la référence horaire | KPI-05, référence = vitesse fluide | Pas assez de jours pour une référence horaire |
| Délai moyen de résolution d'une alerte | **Non retenu** | Les alertes se résolvent automatiquement à la fin de l'épisode : le délai de résolution répète la durée de l'épisode (KPI-02) |
| Part de capteurs muets | **Non retenu** | Demande l'activité par capteur, absente de `fact_traffic_window` ; à reprendre avec les alertes `SENSOR_FAULT` (KPI-04 les compte déjà par type) |
| Taux de rejet de qualité | **Non retenu comme vue** | Le dénominateur (lignes lues) est dans MongoDB (`processing_stats`), pas dans l'entrepôt ; le taux est déjà journalisé par DAT-04 |
| (absent) | KPI-02, KPI-03, KPI-04 | Demandés par l'issue #61 : indicateurs de congestion |

## 6. Points ouverts

- **Définition de « congestion ».** Elle vient de l'ADR-028 (statut « Proposée »). Si le professeur la définit autrement, KPI-01 à KPI-03 changent de valeur sans changer de forme.
  [À COMPLÉTER par les deux membres après validation du professeur]
- **Seuil 0,35 dupliqué.** Il est écrit dans la vue KPI-03 et dans le classificateur (IA-01). Quand le classificateur existera, un test doit les comparer.
- **API et tableau de bord.** EXG-DON-01 exige aussi que la valeur affichée égale celle de l'API : l'API de consultation et le tableau de bord n'existent pas encore. Cette moitié reste à prouver (BE-04, FE-04).
- **Aucune donnée réelle chargée.** Les vues sont vides tant que le chargement des fenêtres, des épisodes et des alertes n'a pas lieu ; la preuve est faite sur un jeu fabriqué. Les épisodes
  et les alertes ne sont pas écrits par un pipeline à ce jour (services de traitement et d'alerte).
- **Évolution d'une vue.** Une migration appliquée ne se réécrit pas : modifier un indicateur après la `0006` demande une nouvelle migration (`DROP VIEW` puis `CREATE VIEW`).
- **Vues matérialisées.** L'ADR-014 les prévoit si le tableau de bord ralentit ; à ce volume, des vues simples suffisent. À mesurer avant de les introduire.
- **Preuve sous Linux.** [À COMPLÉTER par Manoa Robel]

## 7. Utiliser un indicateur

```sql
-- les tronçons les plus congestionnés d'un run, un jour donné (fenêtres d'une minute)
SELECT road_segment_id, part_congestionne, inconnu_s
FROM dwh.kpi_part_temps_congestionne
WHERE run_id = 'demo-2026-10-30' AND jour = DATE '2026-10-30' AND window_size_s = 60
ORDER BY part_congestionne DESC NULLS LAST;
```

Toujours filtrer sur `run_id` (ou afficher `source_type`) : sans cela, deux exécutions se mélangent.
