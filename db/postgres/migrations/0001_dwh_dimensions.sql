-- 0001 · Entrepôt décisionnel (schéma dwh) : tables de dimensions.
-- Modèle en étoile (ADR-014). Vocabulaire et unités : docs/03-donnees/dictionnaire-de-donnees.md.
-- Les identifiants métier (texte) sont stables et partagés avec les événements ;
-- les clés techniques (*_key) sont propres à l'entrepôt.

CREATE TABLE dwh.dim_source (
    source_type text PRIMARY KEY,
    description text NOT NULL
);
COMMENT ON TABLE dwh.dim_source IS 'Origine d''une donnée : mesure réelle, historique réel ou simulation (provenance explicite, ADR-027).';

CREATE TABLE dwh.dim_congestion_state (
    state_code text PRIMARY KEY,
    severity_rank smallint NOT NULL UNIQUE CHECK (severity_rank BETWEEN 0 AND 3),
    label_fr text NOT NULL
);
COMMENT ON TABLE dwh.dim_congestion_state IS 'États de circulation d''un tronçon sur une fenêtre (ADR-028). UNKNOWN : données insuffisantes.';

CREATE TABLE dwh.dim_date (
    date_key        integer PRIMARY KEY CHECK (date_key BETWEEN 20000101 AND 20991231),
    full_date       date NOT NULL UNIQUE,
    year            smallint NOT NULL,
    month           smallint NOT NULL CHECK (month BETWEEN 1 AND 12),
    day             smallint NOT NULL CHECK (day BETWEEN 1 AND 31),
    iso_day_of_week smallint NOT NULL CHECK (iso_day_of_week BETWEEN 1 AND 7),
    iso_week        smallint NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
    is_weekend      boolean NOT NULL,
    is_holiday      boolean NOT NULL DEFAULT false,
    holiday_name    text
);
COMMENT ON TABLE dwh.dim_date IS 'Calendrier (UTC). is_holiday vaut false tant que le calendrier des jours fériés du jeu de données n''est pas chargé : limite connue.';
COMMENT ON COLUMN dwh.dim_date.iso_day_of_week IS '1 = lundi … 7 = dimanche (norme ISO 8601).';

CREATE TABLE dwh.dim_intersection (
    intersection_key  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    intersection_id   text NOT NULL UNIQUE CHECK (intersection_id ~ '^INT_[0-9]{2,}$'),
    name              text NOT NULL,
    latitude          numeric(9, 6) CHECK (latitude BETWEEN -90 AND 90),
    longitude         numeric(9, 6) CHECK (longitude BETWEEN -180 AND 180),
    has_traffic_light boolean NOT NULL DEFAULT true,
    CHECK ((latitude IS NULL) = (longitude IS NULL))
);
COMMENT ON TABLE dwh.dim_intersection IS 'Carrefours. Clé de partition des événements (ADR-009). Coordonnées vides pour le réseau de démonstration (fictif).';

CREATE TABLE dwh.dim_road_segment (
    road_segment_key    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    road_segment_id     text NOT NULL UNIQUE CHECK (road_segment_id ~ '^ROAD_[0-9]{3,}$'),
    intersection_key    integer NOT NULL REFERENCES dwh.dim_intersection (intersection_key),
    name                text NOT NULL,
    approach            text NOT NULL CHECK (approach IN ('N', 'E', 'S', 'W')),
    road_type           text NOT NULL CHECK (road_type IN ('MOTORWAY', 'ARTERIAL', 'COLLECTOR', 'LOCAL')),
    lane_count          smallint NOT NULL CHECK (lane_count BETWEEN 1 AND 8),
    length_m            numeric(7, 1) NOT NULL CHECK (length_m > 0),
    speed_limit_kmh     smallint NOT NULL CHECK (speed_limit_kmh BETWEEN 5 AND 130),
    free_flow_speed_kmh numeric(5, 1) NOT NULL CHECK (free_flow_speed_kmh > 0),
    UNIQUE (intersection_key, approach)
);
COMMENT ON TABLE dwh.dim_road_segment IS 'Tronçons d''approche d''un carrefour : unité d''analyse de la circulation.';
COMMENT ON COLUMN dwh.dim_road_segment.free_flow_speed_kmh IS 'Vitesse en circulation fluide (km/h) : dénominateur du ratio de vitesse. Simulation : égale à la vitesse limite.';
COMMENT ON COLUMN dwh.dim_road_segment.approach IS 'Côté du carrefour d''où arrive la circulation : N, E, S ou W.';

CREATE TABLE dwh.dim_sensor (
    sensor_key           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id            text NOT NULL UNIQUE CHECK (sensor_id ~ '^SENSOR_[0-9]{3,}$'),
    road_segment_key     integer NOT NULL REFERENCES dwh.dim_road_segment (road_segment_key),
    sensor_type          text NOT NULL CHECK (sensor_type IN ('LOOP', 'CAMERA', 'RADAR', 'SIMULATED')),
    reporting_interval_s smallint NOT NULL DEFAULT 10 CHECK (reporting_interval_s BETWEEN 1 AND 3600)
);
COMMENT ON COLUMN dwh.dim_sensor.reporting_interval_s IS 'Durée (secondes) couverte par chaque mesure brute du capteur.';

CREATE INDEX dim_road_segment_intersection_idx ON dwh.dim_road_segment (intersection_key);
CREATE INDEX dim_sensor_segment_idx ON dwh.dim_sensor (road_segment_key);
