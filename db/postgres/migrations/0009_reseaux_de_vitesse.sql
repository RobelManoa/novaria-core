-- Réseaux de mesures de vitesse (IA-16, ADR-032) : des séries de vitesses sans comptage ni occupation, chargées par fichier.
--
-- Pourquoi des tables à part : `dwh.fact_traffic_window` exige un comptage de véhicules (`vehicle_count` NOT NULL, et une vitesse n'existe que
-- s'il y en a au moins un). Un jeu comme METR-LA ne mesure que des vitesses : lui inventer des comptages serait fausser la donnée. Ces tables
-- ne reçoivent QUE ce qui a été mesuré (une vitesse absente n'a pas de ligne). Un réseau s'ajoute par un fichier de description et un fichier
-- de mesures (`data/etl/pipelines/charger_vitesses.py`) : aucune migration par réseau, aucun code à changer pour 100 capteurs de plus.
-- Les réseaux de vitesse n'entrent jamais dans la vue `dwh.v_indicator` : l'état public du réseau fictif n'en est pas touché.

CREATE TABLE dwh.speed_network (
    network_id   text PRIMARY KEY CHECK (network_id ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
    label        text NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
    description  text NOT NULL DEFAULT '',
    source_type  text NOT NULL REFERENCES dwh.dim_source (source_type),
    step_s       smallint NOT NULL CHECK (step_s IN (60, 300)),
    speed_unit   text NOT NULL CHECK (speed_unit IN ('mph', 'kmh')),
    loaded_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dwh.speed_sensor (
    network_id   text NOT NULL REFERENCES dwh.speed_network (network_id) ON DELETE CASCADE,
    sensor_key   integer NOT NULL CHECK (sensor_key >= 0),  -- rang stable dans le réseau
    sensor_id    text NOT NULL CHECK (length(sensor_id) BETWEEN 1 AND 40),
    PRIMARY KEY (network_id, sensor_key),
    UNIQUE (network_id, sensor_id)
);

CREATE TABLE dwh.fact_speed_window (
    network_id   text NOT NULL,
    observed_at  timestamptz NOT NULL,  -- instant du pas, tel que donné par la source (METR-LA : heure murale lue comme UTC)
    sensor_key   integer NOT NULL,
    speed        numeric(6, 2) NOT NULL CHECK (speed > 0 AND speed < 300),  -- dans l'unité du réseau
    PRIMARY KEY (network_id, observed_at, sensor_key),
    FOREIGN KEY (network_id, sensor_key) REFERENCES dwh.speed_sensor (network_id, sensor_key) ON DELETE CASCADE
);
