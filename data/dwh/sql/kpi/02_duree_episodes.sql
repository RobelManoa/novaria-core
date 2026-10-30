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
