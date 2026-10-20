-- 0005 · Réseau de démonstration fictif : 6 carrefours, 24 tronçons d'approche, 24 capteurs simulés.
-- Généré par scripts/dev/gen_reseau.py (ne pas modifier à la main).
-- Vitesse en circulation fluide = vitesse limite (hypothèse de simulation).

INSERT INTO dwh.dim_intersection (intersection_id, name) VALUES
    ('INT_01', 'Carrefour 01'),
    ('INT_02', 'Carrefour 02'),
    ('INT_03', 'Carrefour 03'),
    ('INT_04', 'Carrefour 04'),
    ('INT_05', 'Carrefour 05'),
    ('INT_06', 'Carrefour 06');

INSERT INTO dwh.dim_road_segment
    (road_segment_id, intersection_key, name, approach, road_type, lane_count, length_m, speed_limit_kmh, free_flow_speed_kmh)
SELECT v.road_segment_id, i.intersection_key, v.name, v.approach, v.road_type, v.lane_count, v.length_m, v.limit_kmh, v.limit_kmh
FROM (VALUES
    ('ROAD_001', 'INT_01', 'Carrefour 01 · approche Nord', 'N', 'ARTERIAL', 2, 300, 50),
    ('ROAD_002', 'INT_01', 'Carrefour 01 · approche Est', 'E', 'ARTERIAL', 2, 300, 50),
    ('ROAD_003', 'INT_01', 'Carrefour 01 · approche Sud', 'S', 'ARTERIAL', 2, 300, 50),
    ('ROAD_004', 'INT_01', 'Carrefour 01 · approche Ouest', 'W', 'ARTERIAL', 2, 300, 50),
    ('ROAD_005', 'INT_02', 'Carrefour 02 · approche Nord', 'N', 'ARTERIAL', 2, 300, 50),
    ('ROAD_006', 'INT_02', 'Carrefour 02 · approche Est', 'E', 'ARTERIAL', 2, 300, 50),
    ('ROAD_007', 'INT_02', 'Carrefour 02 · approche Sud', 'S', 'ARTERIAL', 2, 300, 50),
    ('ROAD_008', 'INT_02', 'Carrefour 02 · approche Ouest', 'W', 'ARTERIAL', 2, 300, 50),
    ('ROAD_009', 'INT_03', 'Carrefour 03 · approche Nord', 'N', 'COLLECTOR', 1, 250, 50),
    ('ROAD_010', 'INT_03', 'Carrefour 03 · approche Est', 'E', 'COLLECTOR', 1, 250, 50),
    ('ROAD_011', 'INT_03', 'Carrefour 03 · approche Sud', 'S', 'COLLECTOR', 1, 250, 50),
    ('ROAD_012', 'INT_03', 'Carrefour 03 · approche Ouest', 'W', 'COLLECTOR', 1, 250, 50),
    ('ROAD_013', 'INT_04', 'Carrefour 04 · approche Nord', 'N', 'COLLECTOR', 1, 250, 50),
    ('ROAD_014', 'INT_04', 'Carrefour 04 · approche Est', 'E', 'COLLECTOR', 1, 250, 50),
    ('ROAD_015', 'INT_04', 'Carrefour 04 · approche Sud', 'S', 'COLLECTOR', 1, 250, 50),
    ('ROAD_016', 'INT_04', 'Carrefour 04 · approche Ouest', 'W', 'COLLECTOR', 1, 250, 50),
    ('ROAD_017', 'INT_05', 'Carrefour 05 · approche Nord', 'N', 'LOCAL', 1, 150, 30),
    ('ROAD_018', 'INT_05', 'Carrefour 05 · approche Est', 'E', 'LOCAL', 1, 150, 30),
    ('ROAD_019', 'INT_05', 'Carrefour 05 · approche Sud', 'S', 'LOCAL', 1, 150, 30),
    ('ROAD_020', 'INT_05', 'Carrefour 05 · approche Ouest', 'W', 'LOCAL', 1, 150, 30),
    ('ROAD_021', 'INT_06', 'Carrefour 06 · approche Nord', 'N', 'LOCAL', 1, 150, 30),
    ('ROAD_022', 'INT_06', 'Carrefour 06 · approche Est', 'E', 'LOCAL', 1, 150, 30),
    ('ROAD_023', 'INT_06', 'Carrefour 06 · approche Sud', 'S', 'LOCAL', 1, 150, 30),
    ('ROAD_024', 'INT_06', 'Carrefour 06 · approche Ouest', 'W', 'LOCAL', 1, 150, 30)
) AS v (road_segment_id, intersection_id, name, approach, road_type, lane_count, length_m, limit_kmh)
JOIN dwh.dim_intersection i ON i.intersection_id = v.intersection_id;

INSERT INTO dwh.dim_sensor (sensor_id, road_segment_key, sensor_type, reporting_interval_s)
SELECT v.sensor_id, s.road_segment_key, 'SIMULATED', 10
FROM (VALUES
    ('SENSOR_001', 'ROAD_001'),
    ('SENSOR_002', 'ROAD_002'),
    ('SENSOR_003', 'ROAD_003'),
    ('SENSOR_004', 'ROAD_004'),
    ('SENSOR_005', 'ROAD_005'),
    ('SENSOR_006', 'ROAD_006'),
    ('SENSOR_007', 'ROAD_007'),
    ('SENSOR_008', 'ROAD_008'),
    ('SENSOR_009', 'ROAD_009'),
    ('SENSOR_010', 'ROAD_010'),
    ('SENSOR_011', 'ROAD_011'),
    ('SENSOR_012', 'ROAD_012'),
    ('SENSOR_013', 'ROAD_013'),
    ('SENSOR_014', 'ROAD_014'),
    ('SENSOR_015', 'ROAD_015'),
    ('SENSOR_016', 'ROAD_016'),
    ('SENSOR_017', 'ROAD_017'),
    ('SENSOR_018', 'ROAD_018'),
    ('SENSOR_019', 'ROAD_019'),
    ('SENSOR_020', 'ROAD_020'),
    ('SENSOR_021', 'ROAD_021'),
    ('SENSOR_022', 'ROAD_022'),
    ('SENSOR_023', 'ROAD_023'),
    ('SENSOR_024', 'ROAD_024')
) AS v (sensor_id, road_segment_id)
JOIN dwh.dim_road_segment s ON s.road_segment_id = v.road_segment_id;
