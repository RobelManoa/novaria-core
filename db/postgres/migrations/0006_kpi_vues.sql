-- 0006 · Vues d'indicateurs décisionnels (DAT-07) : cinq vues dwh.kpi_*, lecture seule.
-- Généré par scripts/dev/gen_kpi.py depuis data/dwh/sql/kpi/ : ne pas modifier à la main.
-- Définitions, sources, limites : docs/03-donnees/kpi.md.

-- ===== 01_part_temps_congestionne.sql =====
-- KPI-01 · Part du temps en état CONGESTED, par tronçon et par jour.
-- Source : dwh.fact_traffic_window (état stabilisé de chaque fenêtre, ADR-028).
-- Calcul : secondes en CONGESTED ÷ secondes observées (fenêtres dont l'état n'est pas UNKNOWN).
-- Une ligne par exécution, tronçon, jour UTC et taille de fenêtre : deux tailles ne s'additionnent jamais (le temps compterait deux fois).
-- Fiche : docs/03-donnees/kpi.md.

CREATE VIEW dwh.kpi_part_temps_congestionne AS
SELECT f.run_id,
       f.source_type,
       s.road_segment_id,
       d.full_date AS jour,
       f.window_size_s,
       coalesce(sum(f.window_size_s) FILTER (WHERE f.congestion_state = 'CONGESTED'), 0) AS congestionne_s,
       coalesce(sum(f.window_size_s) FILTER (WHERE f.congestion_state <> 'UNKNOWN'), 0) AS observe_s,
       coalesce(sum(f.window_size_s) FILTER (WHERE f.congestion_state = 'UNKNOWN'), 0) AS inconnu_s,
       round(coalesce(sum(f.window_size_s) FILTER (WHERE f.congestion_state = 'CONGESTED'), 0)::numeric
             / nullif(sum(f.window_size_s) FILTER (WHERE f.congestion_state <> 'UNKNOWN'), 0), 4) AS part_congestionne
FROM dwh.fact_traffic_window f
JOIN dwh.dim_road_segment s ON s.road_segment_key = f.road_segment_key
JOIN dwh.dim_date d ON d.date_key = f.date_key
GROUP BY f.run_id, f.source_type, s.road_segment_id, d.full_date, f.window_size_s;

COMMENT ON VIEW dwh.kpi_part_temps_congestionne IS 'KPI-01 : part du temps observé passée en état CONGESTED, par exécution, tronçon, jour UTC et taille de fenêtre. NULL si rien n''a été observé (tout UNKNOWN).';
COMMENT ON COLUMN dwh.kpi_part_temps_congestionne.observe_s IS 'Secondes de fenêtres dont l''état est connu (hors UNKNOWN) : le dénominateur.';

-- ===== 02_duree_episodes.sql =====
-- KPI-02 · Durée moyenne des épisodes de dégradation, par tronçon, jour de début et état le plus grave atteint.
-- Source : dwh.fact_congestion_episode (ADR-028 : ouverture quand l'état quitte FREE_FLOW, clôture au retour à FREE_FLOW).
-- Calcul : moyenne de (ended_at - started_at) en secondes sur les épisodes clos ; les épisodes en cours (ended_at NULL) sont comptés à part et exclus de la moyenne.
-- Les épisodes de congestion sont ceux dont peak_state vaut CONGESTED ; les autres n'ont atteint que SLOW.
-- Fiche : docs/03-donnees/kpi.md.

CREATE VIEW dwh.kpi_duree_episodes AS
SELECT e.run_id,
       e.source_type,
       s.road_segment_id,
       (e.started_at AT TIME ZONE 'UTC')::date AS jour,
       e.peak_state,
       count(*) FILTER (WHERE e.ended_at IS NOT NULL) AS episodes_clos,
       count(*) FILTER (WHERE e.ended_at IS NULL) AS episodes_en_cours,
       round((avg(extract(epoch FROM e.ended_at - e.started_at)) FILTER (WHERE e.ended_at IS NOT NULL))::numeric, 1) AS duree_moyenne_s,
       round((max(extract(epoch FROM e.ended_at - e.started_at)) FILTER (WHERE e.ended_at IS NOT NULL))::numeric, 1) AS duree_max_s
FROM dwh.fact_congestion_episode e
JOIN dwh.dim_road_segment s ON s.road_segment_key = e.road_segment_key
GROUP BY e.run_id, e.source_type, s.road_segment_id, (e.started_at AT TIME ZONE 'UTC')::date, e.peak_state;

COMMENT ON VIEW dwh.kpi_duree_episodes IS 'KPI-02 : durée moyenne et maximale des épisodes clos, par exécution, tronçon, jour UTC de début et état le plus grave (peak_state). Les épisodes en cours sont comptés dans episodes_en_cours, jamais dans la moyenne.';

-- ===== 03_delai_detection.sql =====
-- KPI-03 · Délai de détection d'une congestion, par jour d'ouverture de l'alerte.
-- Sources : alertes.alert (alertes de type CONGESTION, ouverture opened_at), dwh.fact_congestion_episode (lien par episode_id,
-- sans clé étrangère entre services, ADR-008) et dwh.fact_traffic_window (ratios de vitesse bruts de l'épisode).
-- Calcul : opened_at de l'alerte - début de la première fenêtre de l'épisode dont le ratio de vitesse est sous le seuil de montée
-- vers CONGESTED (0,35, valeur de départ de l'ADR-028, à tenir égale à celle du classificateur). Ce délai contient donc la confirmation
-- par l'hystérésis (2 fenêtres) et la latence de la chaîne, mais pas l'écart à la vérité terrain du générateur (mesuré en IA-03).
-- Une alerte dont le délai ne peut pas se calculer (épisode ou observation absents, ou ouverture antérieure à l'observation) est comptée dans
-- `alertes` mais pas dans `alertes_mesurees` : le trou se voit au lieu de se cacher.
-- Fiche : docs/03-donnees/kpi.md.

CREATE VIEW dwh.kpi_delai_detection AS
WITH seuil AS (
    SELECT 0.35::numeric AS ratio_montee
),
alerte_et_observation AS (
    SELECT a.alert_id,
           a.run_id,
           a.source_type,
           (a.opened_at AT TIME ZONE 'UTC')::date AS jour,
           a.opened_at,
           (SELECT min(w.window_start)
              FROM dwh.fact_traffic_window w
             WHERE w.road_segment_key = e.road_segment_key
               AND w.run_id = e.run_id
               AND w.window_start >= e.started_at
               AND (e.ended_at IS NULL OR w.window_start < e.ended_at)
               AND w.speed_ratio < (SELECT ratio_montee FROM seuil)) AS premiere_observation
    FROM alertes.alert a
    LEFT JOIN dwh.fact_congestion_episode e ON e.episode_id = a.episode_id
    WHERE a.kind = 'CONGESTION'
),
delai AS (
    SELECT o.*,
           CASE WHEN o.premiere_observation IS NOT NULL AND o.opened_at >= o.premiere_observation
                THEN extract(epoch FROM o.opened_at - o.premiere_observation)
           END AS delai_s
    FROM alerte_et_observation o
)
SELECT run_id,
       source_type,
       jour,
       count(*) AS alertes,
       count(delai_s) AS alertes_mesurees,
       round(avg(delai_s)::numeric, 1) AS delai_moyen_s,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY delai_s))::numeric, 1) AS delai_median_s,
       round(max(delai_s)::numeric, 1) AS delai_max_s
FROM delai
GROUP BY run_id, source_type, jour;

COMMENT ON VIEW dwh.kpi_delai_detection IS 'KPI-03 : délai entre la première fenêtre d''un épisode sous le seuil de montée (ratio 0,35) et l''ouverture de l''alerte de congestion, par exécution et jour UTC. alertes - alertes_mesurees = alertes dont le délai est incalculable.';

-- ===== 04_alertes_par_jour.sql =====
-- KPI-04 · Alertes par jour et par type.
-- Source : alertes.alert (une alerte par épisode, ADR-028 ; jamais une alerte par mesure).
-- Calcul : nombre d'alertes ouvertes le jour UTC de opened_at, dont celles résolues (état RESOLVED) et celles qui ne le sont pas.
-- Ce nombre ne dit pas combien d'alertes étaient justifiées : les fausses alertes demandent la vérité terrain du générateur (IA-03).
-- Fiche : docs/03-donnees/kpi.md.

CREATE VIEW dwh.kpi_alertes_par_jour AS
SELECT a.run_id,
       a.source_type,
       (a.opened_at AT TIME ZONE 'UTC')::date AS jour,
       a.kind,
       count(*) AS alertes,
       count(*) FILTER (WHERE a.state = 'RESOLVED') AS resolues,
       count(*) FILTER (WHERE a.state <> 'RESOLVED') AS non_resolues
FROM alertes.alert a
GROUP BY a.run_id, a.source_type, (a.opened_at AT TIME ZONE 'UTC')::date, a.kind;

COMMENT ON VIEW dwh.kpi_alertes_par_jour IS 'KPI-04 : alertes ouvertes par exécution, jour UTC et type (kind), avec le nombre de résolues et de non résolues.';

-- ===== 05_vitesse_relative_horaire.sql =====
-- KPI-05 · Vitesse relative (vitesse ÷ vitesse fluide du tronçon) par tronçon, jour et heure UTC.
-- Source : dwh.fact_traffic_window (speed_ratio, vehicle_count).
-- Calcul : moyenne des ratios pondérée par le nombre de véhicules, sur les fenêtres qui ont un ratio (au moins un véhicule). 1 = circulation fluide.
-- Une ligne par exécution, tronçon, jour, heure et taille de fenêtre. Sans véhicule, aucun ratio : la route vide n'est pas une route arrêtée.
-- Fiche : docs/03-donnees/kpi.md.

CREATE VIEW dwh.kpi_vitesse_relative_horaire AS
SELECT f.run_id,
       f.source_type,
       s.road_segment_id,
       d.full_date AS jour,
       extract(hour FROM f.window_start AT TIME ZONE 'UTC')::integer AS heure,
       f.window_size_s,
       count(*) AS fenetres,
       count(f.speed_ratio) AS fenetres_avec_vitesse,
       sum(f.vehicle_count) AS vehicules,
       round(sum(f.speed_ratio * f.vehicle_count) / nullif(sum(f.vehicle_count) FILTER (WHERE f.speed_ratio IS NOT NULL), 0), 3) AS vitesse_relative
FROM dwh.fact_traffic_window f
JOIN dwh.dim_road_segment s ON s.road_segment_key = f.road_segment_key
JOIN dwh.dim_date d ON d.date_key = f.date_key
GROUP BY f.run_id, f.source_type, s.road_segment_id, d.full_date, extract(hour FROM f.window_start AT TIME ZONE 'UTC')::integer, f.window_size_s;

COMMENT ON VIEW dwh.kpi_vitesse_relative_horaire IS 'KPI-05 : vitesse relative moyenne pondérée par les véhicules, par exécution, tronçon, jour et heure UTC. NULL si aucune fenêtre n''a de ratio.';
