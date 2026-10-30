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
