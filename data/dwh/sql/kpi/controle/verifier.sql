-- Contrôle de recalcul des cinq indicateurs (DAT-07) : « chaque indicateur se recalcule à partir de la source annoncée ».
--
-- Lancement (base migrée, compte administrateur) :  python scripts/dev/dev.py db-check-kpi
--
-- Le script insère un petit jeu fabriqué (exécution `kpi-controle`, source SIMULATED, valeurs inventées) dans UNE transaction
-- qu'il annule à la fin : rien ne reste en base. Pour chaque indicateur, trois valeurs sont comparées :
--   vue      : ce que renvoie la vue dwh.kpi_* ;
--   recalcul : la même grandeur recalculée directement sur les tables sources, SANS la vue et avec une autre formulation ;
--   attendu  : le résultat calculé à la main (voir docs/03-donnees/kpi.md, section 4).
-- Un écart lève une exception : le script s'arrête avec un code d'erreur.

\set ON_ERROR_STOP on
BEGIN;

-- ---------------------------------------------------------------------------------------------------------------
-- Jeu de contrôle. Tronçons du réseau de démonstration : ROAD_001 et ROAD_002 (carrefour INT_01), vitesse fluide 50 km/h.
-- Fenêtres de 60 s, le 2026-10-30 (UTC). Colonnes : tronçon, début, véhicules, ratio de vitesse, état stabilisé.
-- La vitesse est ratio × 50 ; une fenêtre sans véhicule n'a ni vitesse ni ratio. Débit = véhicules (fenêtre d'une minute).
-- ---------------------------------------------------------------------------------------------------------------
INSERT INTO dwh.fact_traffic_window
    (road_segment_key, window_start, window_size_s, run_id, source_type, vehicle_count, flow_veh_per_min,
     average_speed_kmh, speed_ratio, sample_count, expected_sample_count, congestion_state, classifier_version)
SELECT s.road_segment_key, v.debut::timestamptz, 60, 'kpi-controle', 'SIMULATED', v.vehicules, v.vehicules,
       v.ratio * 50, v.ratio, CASE WHEN v.etat = 'UNKNOWN' THEN 2 ELSE 10 END, 10, v.etat, 'regles-v0'
FROM (VALUES
    -- ROAD_001, premier épisode (E1) : ralentissement dès 10:02, ratio brut sous 0,35 à partir de 10:04, CONGESTED confirmé à 10:05
    ('ROAD_001', '2026-10-30T10:00:00Z', 20, 0.90, 'FREE_FLOW'),
    ('ROAD_001', '2026-10-30T10:01:00Z', 20, 0.80, 'FREE_FLOW'),
    ('ROAD_001', '2026-10-30T10:02:00Z', 18, 0.50, 'SLOW'),
    ('ROAD_001', '2026-10-30T10:03:00Z', 16, 0.40, 'SLOW'),
    ('ROAD_001', '2026-10-30T10:04:00Z', 14, 0.30, 'SLOW'),
    ('ROAD_001', '2026-10-30T10:05:00Z', 12, 0.30, 'CONGESTED'),
    ('ROAD_001', '2026-10-30T10:06:00Z', 10, 0.20, 'CONGESTED'),
    ('ROAD_001', '2026-10-30T10:07:00Z', 10, 0.30, 'CONGESTED'),
    ('ROAD_001', '2026-10-30T10:08:00Z', 14, 0.50, 'SLOW'),
    ('ROAD_001', '2026-10-30T10:09:00Z', 20, 0.90, 'FREE_FLOW'),
    -- fenêtres sans mesure suffisante : état UNKNOWN, ni vitesse ni ratio ; la seconde a pourtant compté 6 véhicules
    ('ROAD_001', '2026-10-30T10:10:00Z', 0, NULL, 'UNKNOWN'),
    ('ROAD_001', '2026-10-30T10:11:00Z', 6, NULL, 'UNKNOWN'),
    -- ROAD_001, deuxième épisode (E2) : ralenti seulement
    ('ROAD_001', '2026-10-30T10:20:00Z', 10, 0.50, 'SLOW'),
    ('ROAD_001', '2026-10-30T10:21:00Z', 10, 0.50, 'SLOW'),
    ('ROAD_001', '2026-10-30T10:22:00Z', 10, 0.50, 'SLOW'),
    ('ROAD_001', '2026-10-30T10:23:00Z', 10, 0.50, 'SLOW'),
    -- ROAD_002 : fluide à 10:29, puis congestion encore en cours (épisode E3 ouvert)
    ('ROAD_002', '2026-10-30T10:29:00Z', 20, 0.90, 'FREE_FLOW'),
    ('ROAD_002', '2026-10-30T10:30:00Z', 8, 0.30, 'CONGESTED'),
    ('ROAD_002', '2026-10-30T10:31:00Z', 8, 0.30, 'CONGESTED'),
    ('ROAD_002', '2026-10-30T10:32:00Z', 8, 0.30, 'CONGESTED'),
    ('ROAD_002', '2026-10-30T10:33:00Z', 8, 0.30, 'CONGESTED'),
    ('ROAD_002', '2026-10-30T10:34:00Z', 8, 0.30, 'CONGESTED')
) AS v (troncon, debut, vehicules, ratio, etat)
JOIN dwh.dim_road_segment s ON s.road_segment_id = v.troncon;

-- Épisodes : E1 (420 s, CONGESTED), E2 (240 s, SLOW), E3 (en cours, CONGESTED), E4 (180 s, CONGESTED, sans fenêtre chargée).
INSERT INTO dwh.fact_congestion_episode
    (episode_id, road_segment_key, run_id, source_type, started_at, ended_at, peak_state, min_speed_ratio, window_count)
SELECT v.episode_id::uuid, s.road_segment_key, 'kpi-controle', 'SIMULATED', v.debut::timestamptz, v.fin::timestamptz, v.pic, v.ratio_min, v.fenetres
FROM (VALUES
    ('e1000000-0000-4000-8000-000000000001', 'ROAD_001', '2026-10-30T10:02:00Z', '2026-10-30T10:09:00Z', 'CONGESTED', 0.200, 7),
    ('e1000000-0000-4000-8000-000000000002', 'ROAD_001', '2026-10-30T10:20:00Z', '2026-10-30T10:24:00Z', 'SLOW', 0.500, 4),
    ('e1000000-0000-4000-8000-000000000003', 'ROAD_002', '2026-10-30T10:30:00Z', NULL, 'CONGESTED', 0.300, 5),
    ('e1000000-0000-4000-8000-000000000004', 'ROAD_001', '2026-10-30T11:00:00Z', '2026-10-30T11:03:00Z', 'CONGESTED', 0.250, 3)
) AS v (episode_id, troncon, debut, fin, pic, ratio_min, fenetres)
JOIN dwh.dim_road_segment s ON s.road_segment_id = v.troncon;

-- Alertes : A1 sur E1 (ouverte 10:06:10, résolue), A2 sur E3 (10:33:00, notifiée), A4 sur E4 (11:02:00, créée),
-- A3 : alerte de capteur muet le lendemain, sans épisode.
INSERT INTO alertes.alert
    (rule_id, kind, road_segment_id, intersection_id, episode_id, run_id, source_type, severity, state, opened_at, notified_at, resolved_at, resolution)
VALUES
    ('congestion.persistante', 'CONGESTION', 'ROAD_001', 'INT_01', 'e1000000-0000-4000-8000-000000000001', 'kpi-controle', 'SIMULATED', 'CRITICAL', 'RESOLVED',
     '2026-10-30T10:06:10Z', '2026-10-30T10:06:15Z', '2026-10-30T10:09:00Z', 'AUTO'),
    ('congestion.persistante', 'CONGESTION', 'ROAD_002', 'INT_01', 'e1000000-0000-4000-8000-000000000003', 'kpi-controle', 'SIMULATED', 'CRITICAL', 'NOTIFIED',
     '2026-10-30T10:33:00Z', '2026-10-30T10:33:05Z', NULL, NULL),
    ('congestion.persistante', 'CONGESTION', 'ROAD_001', 'INT_01', 'e1000000-0000-4000-8000-000000000004', 'kpi-controle', 'SIMULATED', 'WARNING', 'CREATED',
     '2026-10-30T11:02:00Z', NULL, NULL, NULL),
    ('capteur.muet', 'SENSOR_FAULT', 'ROAD_001', 'INT_01', NULL, 'kpi-controle', 'SIMULATED', 'WARNING', 'CREATED',
     '2026-10-31T08:00:00Z', NULL, NULL, NULL);

-- ---------------------------------------------------------------------------------------------------------------
-- Comparaisons : vue, recalcul sur les sources, valeur attendue à la main. Tout est comparé en texte.
-- ---------------------------------------------------------------------------------------------------------------
CREATE TEMP TABLE controle (rang serial, kpi text, grandeur text, vue text, recalcul text, attendu text) ON COMMIT DROP;

-- KPI-01 : part du temps en CONGESTED. Recalcul : nombre de fenêtres × 60 s, comptées avec count(*).
INSERT INTO controle (kpi, grandeur, vue, recalcul, attendu)
SELECT 'KPI-01', t.troncon || ' · ' || g.nom,
       CASE g.nom WHEN 'congestionne_s' THEN v.congestionne_s::text WHEN 'observe_s' THEN v.observe_s::text
                  WHEN 'inconnu_s' THEN v.inconnu_s::text ELSE v.part_congestionne::text END,
       CASE g.nom
            WHEN 'congestionne_s' THEN (c.congestionnees * 60)::text
            WHEN 'observe_s' THEN (c.connues * 60)::text
            WHEN 'inconnu_s' THEN (c.inconnues * 60)::text
            ELSE round(c.congestionnees::numeric / c.connues, 4)::text END,
       CASE t.troncon || g.nom
            WHEN 'ROAD_001congestionne_s' THEN '180' WHEN 'ROAD_001observe_s' THEN '840' WHEN 'ROAD_001inconnu_s' THEN '120'
            WHEN 'ROAD_001part_congestionne' THEN '0.2143'
            WHEN 'ROAD_002congestionne_s' THEN '300' WHEN 'ROAD_002observe_s' THEN '360' WHEN 'ROAD_002inconnu_s' THEN '0'
            ELSE '0.8333' END
FROM (VALUES ('ROAD_001'), ('ROAD_002')) AS t (troncon)
CROSS JOIN (VALUES ('congestionne_s'), ('observe_s'), ('inconnu_s'), ('part_congestionne')) AS g (nom)
JOIN dwh.kpi_part_temps_congestionne v ON v.run_id = 'kpi-controle' AND v.road_segment_id = t.troncon AND v.jour = DATE '2026-10-30'
CROSS JOIN LATERAL (
    SELECT count(*) FILTER (WHERE w.congestion_state = 'CONGESTED') AS congestionnees,
           count(*) FILTER (WHERE w.congestion_state NOT IN ('UNKNOWN')) AS connues,
           count(*) FILTER (WHERE w.congestion_state = 'UNKNOWN') AS inconnues
    FROM dwh.fact_traffic_window w
    WHERE w.run_id = 'kpi-controle'
      AND w.road_segment_key = (SELECT road_segment_key FROM dwh.dim_road_segment WHERE road_segment_id = t.troncon)
      AND w.window_start >= TIMESTAMPTZ '2026-10-30T00:00:00Z' AND w.window_start < TIMESTAMPTZ '2026-10-31T00:00:00Z'
) c;

-- KPI-02 : durée des épisodes. Recalcul : différence des secondes écoulées depuis 1970, somme puis division.
INSERT INTO controle (kpi, grandeur, vue, recalcul, attendu)
SELECT 'KPI-02', t.troncon || ' · ' || t.etat || ' · ' || g.nom,
       CASE g.nom WHEN 'episodes_clos' THEN v.episodes_clos::text WHEN 'episodes_en_cours' THEN v.episodes_en_cours::text
                  WHEN 'duree_moyenne_s' THEN coalesce(v.duree_moyenne_s::text, 'NULL') ELSE coalesce(v.duree_max_s::text, 'NULL') END,
       CASE g.nom WHEN 'episodes_clos' THEN c.clos::text WHEN 'episodes_en_cours' THEN c.en_cours::text
                  WHEN 'duree_moyenne_s' THEN coalesce(round(c.total_s / nullif(c.clos, 0), 1)::text, 'NULL') ELSE coalesce(round(c.maximum_s, 1)::text, 'NULL') END,
       CASE t.troncon || t.etat || g.nom
            WHEN 'ROAD_001CONGESTEDepisodes_clos' THEN '2' WHEN 'ROAD_001CONGESTEDepisodes_en_cours' THEN '0'
            WHEN 'ROAD_001CONGESTEDduree_moyenne_s' THEN '300.0' WHEN 'ROAD_001CONGESTEDduree_max_s' THEN '420.0'
            WHEN 'ROAD_001SLOWepisodes_clos' THEN '1' WHEN 'ROAD_001SLOWepisodes_en_cours' THEN '0'
            WHEN 'ROAD_001SLOWduree_moyenne_s' THEN '240.0' WHEN 'ROAD_001SLOWduree_max_s' THEN '240.0'
            WHEN 'ROAD_002CONGESTEDepisodes_clos' THEN '0' WHEN 'ROAD_002CONGESTEDepisodes_en_cours' THEN '1'
            ELSE 'NULL' END
FROM (VALUES ('ROAD_001', 'CONGESTED'), ('ROAD_001', 'SLOW'), ('ROAD_002', 'CONGESTED')) AS t (troncon, etat)
CROSS JOIN (VALUES ('episodes_clos'), ('episodes_en_cours'), ('duree_moyenne_s'), ('duree_max_s')) AS g (nom)
JOIN dwh.kpi_duree_episodes v ON v.run_id = 'kpi-controle' AND v.road_segment_id = t.troncon AND v.peak_state = t.etat AND v.jour = DATE '2026-10-30'
CROSS JOIN LATERAL (
    SELECT count(*) FILTER (WHERE e.ended_at IS NOT NULL) AS clos,
           count(*) FILTER (WHERE e.ended_at IS NULL) AS en_cours,
           coalesce(sum(date_part('epoch', e.ended_at) - date_part('epoch', e.started_at)), 0)::numeric AS total_s,
           max(date_part('epoch', e.ended_at) - date_part('epoch', e.started_at))::numeric AS maximum_s
    FROM dwh.fact_congestion_episode e
    WHERE e.run_id = 'kpi-controle' AND e.peak_state = t.etat
      AND e.road_segment_key = (SELECT road_segment_key FROM dwh.dim_road_segment WHERE road_segment_id = t.troncon)
) c;

-- KPI-03 : délai de détection. Recalcul : une jointure latérale par alerte, médiane lue dans un tableau trié.
INSERT INTO controle (kpi, grandeur, vue, recalcul, attendu)
WITH delais AS (
    SELECT a.alert_id, round(date_part('epoch', a.opened_at) - date_part('epoch', o.debut))::numeric AS delai
    FROM alertes.alert a
    JOIN dwh.fact_congestion_episode e ON e.episode_id = a.episode_id
    CROSS JOIN LATERAL (
        SELECT w.window_start AS debut
        FROM dwh.fact_traffic_window w
        WHERE w.road_segment_key = e.road_segment_key AND w.run_id = e.run_id AND w.speed_ratio < 0.35
          AND w.window_start >= e.started_at AND coalesce(e.ended_at > w.window_start, true)
        ORDER BY w.window_start
        LIMIT 1
    ) o
    WHERE a.run_id = 'kpi-controle' AND a.kind = 'CONGESTION' AND a.opened_at >= o.debut
),
agregat AS (
    SELECT (SELECT count(*) FROM alertes.alert WHERE run_id = 'kpi-controle' AND kind = 'CONGESTION'
                AND opened_at >= TIMESTAMPTZ '2026-10-30T00:00:00Z' AND opened_at < TIMESTAMPTZ '2026-10-31T00:00:00Z') AS alertes,
           count(*) AS mesurees,
           sum(delai) / count(*) AS moyenne,
           (array_agg(delai ORDER BY delai))[((count(*) + 1) / 2)::integer] AS bas,
           (array_agg(delai ORDER BY delai))[((count(*) + 2) / 2)::integer] AS haut,
           max(delai) AS maximum
    FROM delais
)
SELECT 'KPI-03', g.nom,
       CASE g.nom WHEN 'alertes' THEN v.alertes::text WHEN 'alertes_mesurees' THEN v.alertes_mesurees::text
                  WHEN 'delai_moyen_s' THEN v.delai_moyen_s::text WHEN 'delai_median_s' THEN v.delai_median_s::text ELSE v.delai_max_s::text END,
       CASE g.nom WHEN 'alertes' THEN a.alertes::text WHEN 'alertes_mesurees' THEN a.mesurees::text
                  WHEN 'delai_moyen_s' THEN round(a.moyenne, 1)::text WHEN 'delai_median_s' THEN round((a.bas + a.haut) / 2, 1)::text
                  ELSE round(a.maximum, 1)::text END,
       CASE g.nom WHEN 'alertes' THEN '3' WHEN 'alertes_mesurees' THEN '2' WHEN 'delai_moyen_s' THEN '155.0'
                  WHEN 'delai_median_s' THEN '155.0' ELSE '180.0' END
FROM (VALUES ('alertes'), ('alertes_mesurees'), ('delai_moyen_s'), ('delai_median_s'), ('delai_max_s')) AS g (nom)
CROSS JOIN agregat a
JOIN dwh.kpi_delai_detection v ON v.run_id = 'kpi-controle' AND v.jour = DATE '2026-10-30';

-- KPI-04 : alertes par jour. Recalcul : trois comptages filtrés sur des bornes de jour explicites.
INSERT INTO controle (kpi, grandeur, vue, recalcul, attendu)
SELECT 'KPI-04', t.jour::text || ' · ' || t.type || ' · ' || g.nom,
       CASE g.nom WHEN 'alertes' THEN v.alertes::text WHEN 'resolues' THEN v.resolues::text ELSE v.non_resolues::text END,
       CASE g.nom WHEN 'alertes' THEN (SELECT count(*) FROM alertes.alert a WHERE a.run_id = 'kpi-controle' AND a.kind = t.type AND a.opened_at >= t.debut AND a.opened_at < t.fin)::text
                  WHEN 'resolues' THEN (SELECT count(*) FROM alertes.alert a WHERE a.run_id = 'kpi-controle' AND a.kind = t.type AND a.opened_at >= t.debut AND a.opened_at < t.fin AND a.resolved_at IS NOT NULL)::text
                  ELSE (SELECT count(*) FROM alertes.alert a WHERE a.run_id = 'kpi-controle' AND a.kind = t.type AND a.opened_at >= t.debut AND a.opened_at < t.fin AND a.resolved_at IS NULL)::text END,
       CASE t.type || g.nom WHEN 'CONGESTIONalertes' THEN '3' WHEN 'CONGESTIONresolues' THEN '1' WHEN 'CONGESTIONnon_resolues' THEN '2'
                  WHEN 'SENSOR_FAULTalertes' THEN '1' WHEN 'SENSOR_FAULTresolues' THEN '0' ELSE '1' END
FROM (VALUES (DATE '2026-10-30', TIMESTAMPTZ '2026-10-30T00:00:00Z', TIMESTAMPTZ '2026-10-31T00:00:00Z', 'CONGESTION'),
             (DATE '2026-10-31', TIMESTAMPTZ '2026-10-31T00:00:00Z', TIMESTAMPTZ '2026-11-01T00:00:00Z', 'SENSOR_FAULT')) AS t (jour, debut, fin, type)
CROSS JOIN (VALUES ('alertes'), ('resolues'), ('non_resolues')) AS g (nom)
JOIN dwh.kpi_alertes_par_jour v ON v.run_id = 'kpi-controle' AND v.jour = t.jour AND v.kind = t.type;

-- KPI-05 : vitesse relative pondérée. Recalcul : somme des produits ratio × véhicules divisée par la somme des véhicules, sans la vue.
INSERT INTO controle (kpi, grandeur, vue, recalcul, attendu)
SELECT 'KPI-05', t.troncon || ' · 10 h · ' || g.nom,
       CASE g.nom WHEN 'fenetres' THEN v.fenetres::text WHEN 'fenetres_avec_vitesse' THEN v.fenetres_avec_vitesse::text
                  WHEN 'vehicules' THEN v.vehicules::text ELSE v.vitesse_relative::text END,
       CASE g.nom WHEN 'fenetres' THEN c.toutes::text WHEN 'fenetres_avec_vitesse' THEN c.avec_ratio::text
                  WHEN 'vehicules' THEN c.vehicules::text ELSE round(c.somme_ponderee / c.vehicules_avec_ratio, 3)::text END,
       CASE t.troncon || g.nom
            WHEN 'ROAD_001fenetres' THEN '16' WHEN 'ROAD_001fenetres_avec_vitesse' THEN '14' WHEN 'ROAD_001vehicules' THEN '200'
            WHEN 'ROAD_001vitesse_relative' THEN '0.553'
            WHEN 'ROAD_002fenetres' THEN '6' WHEN 'ROAD_002fenetres_avec_vitesse' THEN '6' WHEN 'ROAD_002vehicules' THEN '60'
            ELSE '0.500' END
FROM (VALUES ('ROAD_001'), ('ROAD_002')) AS t (troncon)
CROSS JOIN (VALUES ('fenetres'), ('fenetres_avec_vitesse'), ('vehicules'), ('vitesse_relative')) AS g (nom)
JOIN dwh.kpi_vitesse_relative_horaire v ON v.run_id = 'kpi-controle' AND v.road_segment_id = t.troncon AND v.jour = DATE '2026-10-30' AND v.heure = 10
CROSS JOIN LATERAL (
    SELECT count(*) AS toutes,
           count(*) FILTER (WHERE w.speed_ratio IS NOT NULL) AS avec_ratio,
           sum(w.vehicle_count) AS vehicules,
           sum(w.vehicle_count) FILTER (WHERE w.speed_ratio IS NOT NULL)::numeric AS vehicules_avec_ratio,
           coalesce(sum(w.speed_ratio * w.vehicle_count), 0) AS somme_ponderee
    FROM dwh.fact_traffic_window w
    WHERE w.run_id = 'kpi-controle'
      AND w.road_segment_key = (SELECT road_segment_key FROM dwh.dim_road_segment WHERE road_segment_id = t.troncon)
      AND w.window_start >= TIMESTAMPTZ '2026-10-30T10:00:00Z' AND w.window_start < TIMESTAMPTZ '2026-10-30T11:00:00Z'
) c;

SELECT kpi, grandeur, vue, recalcul, attendu,
       CASE WHEN vue = recalcul AND recalcul = attendu THEN 'OK' ELSE 'ÉCART' END AS verdict
FROM controle
ORDER BY rang;

DO $verification$
DECLARE
    ecarts integer;
    verifies integer;
BEGIN
    SELECT count(*) FILTER (WHERE vue IS DISTINCT FROM recalcul OR recalcul IS DISTINCT FROM attendu), count(*) INTO ecarts, verifies FROM controle;
    IF verifies <> 39 THEN
        RAISE EXCEPTION 'KPI : % comparaisons au lieu de 39 : un indicateur n''a pas rendu de ligne', verifies;
    END IF;
    IF ecarts > 0 THEN
        RAISE EXCEPTION 'KPI : % écart(s) sur % comparaisons', ecarts, verifies;
    END IF;
    RAISE NOTICE 'KPI : % comparaisons, aucun écart entre la vue, le recalcul sur les sources et la valeur attendue', verifies;
END
$verification$;

ROLLBACK;
