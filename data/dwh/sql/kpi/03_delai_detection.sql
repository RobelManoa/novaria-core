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
