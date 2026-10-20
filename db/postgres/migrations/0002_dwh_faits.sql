-- 0002 · Entrepôt décisionnel (schéma dwh) : tables de faits et rejets d'ETL.
-- Grain de fact_traffic_window : un tronçon, une fenêtre de temps, une exécution (run_id).
-- La clé primaire sert de clé d'idempotence : rejouer un chargement met à jour la ligne, ne la duplique pas
-- (ADR-011, ADR-013).

CREATE TABLE dwh.fact_traffic_window (
    road_segment_key      integer NOT NULL REFERENCES dwh.dim_road_segment (road_segment_key),
    window_start          timestamptz NOT NULL,
    window_size_s         smallint NOT NULL CHECK (window_size_s IN (60, 300)),
    run_id                text NOT NULL CHECK (length(run_id) BETWEEN 1 AND 80),
    source_type           text NOT NULL REFERENCES dwh.dim_source (source_type),
    date_key              integer GENERATED ALWAYS AS (
                              (extract(year  FROM (window_start AT TIME ZONE 'UTC'))::integer * 10000)
                            + (extract(month FROM (window_start AT TIME ZONE 'UTC'))::integer * 100)
                            +  extract(day   FROM (window_start AT TIME ZONE 'UTC'))::integer
                          ) STORED REFERENCES dwh.dim_date (date_key),
    vehicle_count         integer NOT NULL CHECK (vehicle_count >= 0),
    flow_veh_per_min      numeric(8, 2) NOT NULL CHECK (flow_veh_per_min >= 0),
    average_speed_kmh     numeric(5, 1) CHECK (average_speed_kmh BETWEEN 0 AND 200),
    occupancy_rate        numeric(4, 3) CHECK (occupancy_rate BETWEEN 0 AND 1),
    max_queue_length_m    numeric(7, 1) CHECK (max_queue_length_m >= 0),
    speed_ratio           numeric(4, 3) CHECK (speed_ratio >= 0),
    sample_count          smallint NOT NULL CHECK (sample_count >= 0),
    expected_sample_count smallint NOT NULL CHECK (expected_sample_count > 0),
    completeness          numeric(4, 3) GENERATED ALWAYS AS (
                              LEAST(1, sample_count::numeric / expected_sample_count)
                          ) STORED,
    congestion_state      text NOT NULL REFERENCES dwh.dim_congestion_state (state_code),
    classifier_version    text NOT NULL,
    loaded_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (road_segment_key, window_start, window_size_s, run_id),
    -- Une vitesse n'existe que si au moins un véhicule a été observé (dictionnaire de données).
    CHECK (average_speed_kmh IS NULL OR vehicle_count > 0)
);
COMMENT ON TABLE dwh.fact_traffic_window IS 'Indicateurs de circulation par tronçon et par fenêtre (1 ou 5 minutes, UTC).';
COMMENT ON COLUMN dwh.fact_traffic_window.window_start IS 'Début de la fenêtre, en UTC.';
COMMENT ON COLUMN dwh.fact_traffic_window.run_id IS 'Exécution d''origine : « live », identifiant d''un run du simulateur ou d''un jeu historique. Empêche deux exécutions de s''écraser.';
COMMENT ON COLUMN dwh.fact_traffic_window.flow_veh_per_min IS 'Débit : véhicules par minute.';
COMMENT ON COLUMN dwh.fact_traffic_window.average_speed_kmh IS 'Vitesse moyenne pondérée par le nombre de véhicules (km/h). NULL si aucun véhicule (une route vide n''est pas une route arrêtée) ou si la mesure est absente.';
COMMENT ON COLUMN dwh.fact_traffic_window.occupancy_rate IS 'Taux d''occupation de 0 à 1.';
COMMENT ON COLUMN dwh.fact_traffic_window.max_queue_length_m IS 'Plus longue file observée dans la fenêtre, en mètres.';
COMMENT ON COLUMN dwh.fact_traffic_window.speed_ratio IS 'Vitesse moyenne divisée par la vitesse en circulation fluide du tronçon (sans unité).';
COMMENT ON COLUMN dwh.fact_traffic_window.completeness IS 'Part des mesures attendues effectivement reçues (0 à 1).';

CREATE INDEX fact_traffic_window_time_idx ON dwh.fact_traffic_window (window_start);
CREATE INDEX fact_traffic_window_state_idx ON dwh.fact_traffic_window (congestion_state, window_start);

CREATE TABLE dwh.fact_congestion_episode (
    episode_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    road_segment_key integer NOT NULL REFERENCES dwh.dim_road_segment (road_segment_key),
    run_id           text NOT NULL,
    source_type      text NOT NULL REFERENCES dwh.dim_source (source_type),
    started_at       timestamptz NOT NULL,
    ended_at         timestamptz,
    peak_state       text NOT NULL REFERENCES dwh.dim_congestion_state (state_code),
    min_speed_ratio  numeric(4, 3) CHECK (min_speed_ratio >= 0),
    window_count     integer NOT NULL DEFAULT 1 CHECK (window_count >= 1),
    UNIQUE (road_segment_key, run_id, started_at),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);
COMMENT ON TABLE dwh.fact_congestion_episode IS 'Épisodes de ralentissement ou de congestion : ouverture et clôture d''un état dégradé persistant (ADR-028). ended_at NULL : épisode en cours.';

CREATE TABLE dwh.etl_reject (
    reject_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rejected_at timestamptz NOT NULL DEFAULT now(),
    dataset     text NOT NULL,
    source_ref  text,
    rule        text NOT NULL,
    reason      text NOT NULL,
    payload     jsonb
);
COMMENT ON TABLE dwh.etl_reject IS 'Lignes refusées par une règle de qualité, avec la règle et le motif (DAT-04). Le taux de rejet se calcule ici.';
CREATE INDEX etl_reject_dataset_idx ON dwh.etl_reject (dataset, rejected_at);
