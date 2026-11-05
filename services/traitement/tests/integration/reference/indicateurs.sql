-- Recalcul de référence des indicateurs, en SQL, depuis les MESURES BRUTES (MS-10).
--
-- Rien ici ne dépend du code Python du service : les agrégats (dictionnaire de données, section 6)
-- et l'état stabilisé (ADR-028, dictionnaire section 7.1) sont réécrits en SQL à partir de la table
-- `ref_measurements` (une ligne par mesure acceptée, sans doublon). Le test compare chaque champ de
-- chaque fenêtre à ce que l'API sert.
--
-- Règles reprises du dictionnaire :
--  * retenues : qualité VALID ou PARTIAL (SUSPECT exclue) ; la mesure appartient à la fenêtre qui
--    contient le DÉBUT de son intervalle (instant moins durée) ;
--  * vitesse : moyenne pondérée par les véhicules, sur les mesures qui ont une vitesse et des
--    véhicules ; occupation : moyenne des valeurs renseignées ; file : maximum ;
--  * ratio : vitesse non arrondie ÷ vitesse fluide du tronçon, plafonné à 9,999 ;
--  * attendu : somme sur les capteurs du tronçon de (taille ÷ intervalle de rapport) ;
--  * arrondis : ceux des colonnes de dwh.fact_traffic_window (débit 2, vitesse 1, occupation 3,
--    file 1, ratio 3), moitié vers le haut (round de numeric) ;
--  * fenêtre fermée : sa fin ne dépasse pas (plus grand début vu du carrefour) - 10 s ;
--  * état : hystérésis sur les fenêtres fermées d'une minute (2 fenêtres pour dégrader, 3 pour
--    récupérer ; seuils 0,60 / 0,35 / 0,45 / 0,70 ; complétude minimale 0,5) ; une route vide est
--    fluide ; après un trou pendant une dégradation, reclassement avec les seuils d'entrée ; une
--    fenêtre de 5 minutes prend l'état de sa dernière minute.
WITH RECURSIVE
sizes(size) AS (VALUES (60), (300)),
base AS (
    SELECT m.run_id, m.road_segment_id, m.vehicle_count, m.speed, m.occupancy, m.queue,
           extract(epoch FROM m.end_time) - m.interval_s AS start_epoch
    FROM ref_measurements m
    WHERE m.status IN ('VALID', 'PARTIAL')
),
agg AS (
    SELECT b.run_id, b.road_segment_id, z.size AS window_size_s,
           to_timestamp((floor(b.start_epoch / z.size) * z.size)::double precision) AS window_start,
           sum(b.vehicle_count) AS vehicles,
           count(*) AS samples,
           sum(b.speed * b.vehicle_count) FILTER (WHERE b.speed IS NOT NULL AND b.vehicle_count > 0) AS speed_num,
           sum(b.vehicle_count)           FILTER (WHERE b.speed IS NOT NULL AND b.vehicle_count > 0) AS speed_den,
           avg(b.occupancy) AS occupancy,
           max(b.queue) AS queue
    FROM base b CROSS JOIN sizes z
    GROUP BY b.run_id, b.road_segment_id, z.size, floor(b.start_epoch / z.size)
),
expected AS (
    SELECT r.road_segment_id, z.size AS window_size_s, r.free_flow_speed_kmh, r.intersection_key,
           greatest(1, sum(greatest(1, z.size / s.reporting_interval_s))) AS expected
    FROM dwh.dim_road_segment r
    JOIN dwh.dim_sensor s ON s.road_segment_key = r.road_segment_key
    CROSS JOIN sizes z
    GROUP BY r.road_segment_id, z.size, r.free_flow_speed_kmh, r.intersection_key
),
latest AS (  -- plus grand début vu par carrefour, toutes qualités confondues (le temps avance aussi avec une mesure suspecte)
    SELECT r.intersection_key, max(extract(epoch FROM m.end_time) - m.interval_s) AS max_start
    FROM ref_measurements m
    JOIN dwh.dim_road_segment r ON r.road_segment_id = m.road_segment_id
    GROUP BY r.intersection_key
),
windows AS (
    SELECT a.run_id, a.road_segment_id, a.window_size_s, a.window_start,
           a.vehicles::int AS vehicle_count,
           round(a.vehicles * 60.0 / a.window_size_s, 2) AS flow_veh_per_min,
           round(a.speed_num / a.speed_den, 1) AS average_speed_kmh,
           round(a.occupancy, 3) AS occupancy_rate,
           round(a.queue, 1) AS max_queue_length_m,
           -- least() ignore NULL en PostgreSQL : sans vitesse, le ratio doit rester NULL
           CASE WHEN a.speed_den IS NULL THEN NULL
                ELSE least(9.999, round(a.speed_num / a.speed_den / e.free_flow_speed_kmh, 3)) END AS speed_ratio,
           a.samples::int AS sample_count,
           e.expected::int AS expected_sample_count,
           least(1, a.samples::numeric / e.expected)::numeric(4, 3) AS completeness,
           least(1, a.samples::numeric / e.expected) AS completeness_exact,
           (extract(epoch FROM a.window_start) + a.window_size_s <= l.max_start - 10) AS closed
    FROM agg a
    JOIN expected e ON e.road_segment_id = a.road_segment_id AND e.window_size_s = a.window_size_s
    JOIN latest l ON l.intersection_key = e.intersection_key
),
series AS (
    SELECT w.*, row_number() OVER (PARTITION BY w.run_id, w.road_segment_id ORDER BY w.window_start) AS rn
    FROM windows w
    WHERE w.window_size_s = 60 AND w.closed
),
states AS (
    SELECT k.run_id, k.road_segment_id, 0::bigint AS rn, 'UNKNOWN'::text AS st,
           0 AS slow, 0 AS cong, 0 AS mid, 0 AS free, NULL::text AS resume
    FROM (SELECT DISTINCT run_id, road_segment_id FROM series) k
    UNION ALL
    SELECT w.run_id, w.road_segment_id, w.rn, n.st, n.slow, n.cong, n.mid, n.free, n.resume
    FROM states s
    JOIN series w ON w.run_id = s.run_id AND w.road_segment_id = s.road_segment_id AND w.rn = s.rn + 1
    CROSS JOIN LATERAL (
        SELECT CASE WHEN w.speed_ratio IS NOT NULL THEN w.speed_ratio
                    WHEN w.vehicle_count = 0 THEN 'Infinity'::numeric END AS r  -- route vide : fluide ; sinon aucune preuve
    ) ev
    CROSS JOIN LATERAL (
        SELECT CASE WHEN s.st <> 'UNKNOWN' THEN s.st
                    WHEN s.resume IN ('SLOW', 'CONGESTED') THEN
                         CASE WHEN ev.r < 0.35 THEN 'CONGESTED' WHEN ev.r < 0.60 THEN 'SLOW' ELSE 'FREE_FLOW' END
                    ELSE 'FREE_FLOW' END AS base
    ) b
    CROSS JOIN LATERAL (
        SELECT CASE WHEN w.completeness_exact >= 0.5 AND ev.r < 0.60 THEN s.slow + 1 ELSE 0 END AS slow,
               CASE WHEN w.completeness_exact >= 0.5 AND ev.r < 0.35 THEN s.cong + 1 ELSE 0 END AS cong,
               CASE WHEN w.completeness_exact >= 0.5 AND ev.r > 0.45 THEN s.mid + 1 ELSE 0 END AS mid,
               CASE WHEN w.completeness_exact >= 0.5 AND ev.r > 0.70 THEN s.free + 1 ELSE 0 END AS free
    ) k
    CROSS JOIN LATERAL (
        SELECT CASE
                 WHEN w.completeness_exact < 0.5 THEN 'UNKNOWN'
                 WHEN ev.r IS NULL THEN
                      CASE WHEN s.st = 'UNKNOWN' AND s.resume IN ('SLOW', 'CONGESTED') THEN 'UNKNOWN'
                           WHEN s.st = 'UNKNOWN' THEN 'FREE_FLOW'
                           ELSE s.st END
                 WHEN b.base = 'FREE_FLOW' THEN
                      CASE WHEN k.cong >= 2 THEN 'CONGESTED' WHEN k.slow >= 2 THEN 'SLOW' ELSE 'FREE_FLOW' END
                 WHEN b.base = 'SLOW' THEN
                      CASE WHEN k.cong >= 2 THEN 'CONGESTED' WHEN k.free >= 3 THEN 'FREE_FLOW' ELSE 'SLOW' END
                 ELSE
                      CASE WHEN k.free >= 3 THEN 'FREE_FLOW' WHEN k.mid >= 3 THEN 'SLOW' ELSE 'CONGESTED' END
               END AS st,
               k.slow, k.cong, k.mid, k.free,
               CASE WHEN w.completeness_exact < 0.5 THEN CASE WHEN s.st = 'UNKNOWN' THEN s.resume ELSE s.st END
                    WHEN ev.r IS NULL AND s.st = 'UNKNOWN' AND s.resume IN ('SLOW', 'CONGESTED') THEN s.resume
               END AS resume
    ) n
)
SELECT w.run_id, w.road_segment_id, w.window_size_s, w.window_start, w.closed,
       w.vehicle_count, w.flow_veh_per_min, w.average_speed_kmh, w.occupancy_rate, w.max_queue_length_m,
       w.speed_ratio, w.sample_count, w.expected_sample_count, w.completeness,
       CASE WHEN w.window_size_s = 60 THEN own.st ELSE last_minute.st END AS congestion_state
FROM windows w
LEFT JOIN states own ON w.window_size_s = 60 AND own.run_id = w.run_id
                    AND own.road_segment_id = w.road_segment_id
                    AND own.rn = (SELECT s.rn FROM series s WHERE s.run_id = w.run_id
                                  AND s.road_segment_id = w.road_segment_id AND s.window_start = w.window_start)
LEFT JOIN LATERAL (
    SELECT st.st
    FROM series s
    JOIN states st ON st.run_id = s.run_id AND st.road_segment_id = s.road_segment_id AND st.rn = s.rn
    WHERE w.window_size_s = 300 AND s.run_id = w.run_id AND s.road_segment_id = w.road_segment_id
      AND s.window_start = w.window_start + interval '4 minutes'
) last_minute ON true
ORDER BY w.window_size_s, w.road_segment_id, w.window_start;
