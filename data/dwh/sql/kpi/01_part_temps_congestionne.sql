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
