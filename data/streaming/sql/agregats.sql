-- Prototype de flux temps réel (DAT-09) : mesures de capteurs lues sur Kafka (iot.raw), agrégées par fenêtre en temps
-- d'événement, résultat écrit dans MongoDB. Flink SQL seul : aucune fonction Python.
--
-- Les jetons à doubles accolades sont remplacés par `streaming/cli.py` avant l'envoi au client SQL (jamais de secret ici) :
--   {{KAFKA_SERVEURS}}  {{SUJET}}  {{GROUPE}}  {{MONGO_URI}}  {{MONGO_BASE}}  {{MONGO_COLLECTION}}
-- Le rendu se fait dans `streaming/sql.py`, qui vérifie qu'il ne reste aucun jeton non remplacé.

SET 'execution.runtime-mode' = 'streaming';
SET 'table.local-time-zone' = 'UTC';
SET 'pipeline.name' = 'novaria-agregats-par-fenetre';
-- Un seul emplacement de tâche (la mémoire de Docker Desktop est limitée) : une partition à la fois suffit au volume simulé.
SET 'parallelism.default' = '1';
-- Une partition sans message ne retient pas le filigrane (sinon la dernière fenêtre ne se ferme jamais).
SET 'table.exec.source.idle-timeout' = '5 s';
-- Retard autorisé de l'ADR-011 : un message en retard de moins de 30 s met à jour la fenêtre déjà écrite.
SET 'table.exec.emit.allow-lateness' = '30 s';
SET 'table.exec.emit.late-fire.enabled' = 'true';
SET 'table.exec.emit.late-fire.delay' = '0 s';
-- L'état des doublons ne grandit pas sans fin : un identifiant déjà vu est oublié après une heure.
SET 'table.exec.state.ttl' = '1 h';

-- Source : l'enveloppe commune des événements (contracts/events/envelope.schema.json) et la donnée de la mesure
-- (iot-measurement.schema.json). Les champs inconnus sont ignorés : les ajouts compatibles du contrat passent.
CREATE TABLE mesures (
  id STRING,
  `time` TIMESTAMP_LTZ(3),
  subject STRING,
  `data` ROW<
    sensor_id STRING,
    road_segment_id STRING,
    intersection_id STRING,
    interval_s INT,
    vehicle_count INT,
    average_speed_kmh DOUBLE,
    occupancy_rate DOUBLE,
    queue_length_m DOUBLE,
    quality ROW<status STRING>,
    provenance ROW<source_type STRING, run_id STRING, scenario_id STRING>
  >,
  -- Filigrane : 10 secondes de désordre admis (ADR-011). Le temps est celui de la mesure, pas celui de l'arrivée.
  WATERMARK FOR `time` AS `time` - INTERVAL '10' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = '{{SUJET}}',
  'properties.bootstrap.servers' = '{{KAFKA_SERVEURS}}',
  'properties.group.id' = '{{GROUPE}}',
  'scan.startup.mode' = 'earliest-offset',
  'format' = 'json',
  'json.ignore-parse-errors' = 'false',
  'json.fail-on-missing-field' = 'false',
  'json.timestamp-format.standard' = 'ISO-8601'
);

-- Résultat : une ligne par tronçon, par début de fenêtre, par taille de fenêtre et par exécution du simulateur. Cette clé rend
-- l'écriture idempotente : rejouer le même flux réécrit les mêmes documents (ADR-011, section 4.1).
CREATE TABLE agregats (
  road_segment_id STRING,
  window_start TIMESTAMP_LTZ(3),
  window_size_s INT,
  run_id STRING,
  window_end TIMESTAMP_LTZ(3),
  intersection_id STRING,
  source_type STRING,
  sample_count BIGINT,
  vehicle_count BIGINT,
  flow_veh_per_min DOUBLE,
  average_speed_kmh DOUBLE,
  occupancy_rate DOUBLE,
  max_queue_length_m DOUBLE,
  non_valid_count BIGINT,
  PRIMARY KEY (road_segment_id, window_start, window_size_s, run_id) NOT ENFORCED
) WITH (
  'connector' = 'mongodb',
  'uri' = '{{MONGO_URI}}',
  'database' = '{{MONGO_BASE}}',
  'collection' = '{{MONGO_COLLECTION}}',
  'sink.buffer-flush.max-rows' = '500',
  'sink.buffer-flush.interval' = '1 s',
  'sink.delivery-guarantee' = 'at-least-once',
  'sink.max-retries' = '3'
);

-- Les deux tailles de fenêtre de l'ADR-011 dans UN SEUL job : 1 minute (alertes) et 5 minutes (tendances).
-- Vitesse moyenne pondérée par le nombre de véhicules, comme dans le service de traitement ; absente (NULL) sans véhicule.
EXECUTE STATEMENT SET
BEGIN
  INSERT INTO agregats
  SELECT
    `data`.road_segment_id,
    TUMBLE_START(`time`, INTERVAL '1' MINUTE),
    CAST(60 AS INT),
    `data`.provenance.run_id,
    TUMBLE_END(`time`, INTERVAL '1' MINUTE),
    MAX(`data`.intersection_id),
    MAX(`data`.provenance.source_type),
    COUNT(*),
    CAST(SUM(`data`.vehicle_count) AS BIGINT),
    ROUND(SUM(`data`.vehicle_count) * 60.0 / 60, 3),
    ROUND(SUM(`data`.average_speed_kmh * `data`.vehicle_count) / NULLIF(SUM(CASE WHEN `data`.average_speed_kmh IS NULL THEN 0 ELSE `data`.vehicle_count END), 0), 3),
    ROUND(AVG(`data`.occupancy_rate), 3),
    MAX(`data`.queue_length_m),
    SUM(CASE WHEN `data`.quality.status = 'VALID' THEN 0 ELSE 1 END)
  FROM mesures
  GROUP BY TUMBLE(`time`, INTERVAL '1' MINUTE), `data`.road_segment_id, `data`.provenance.run_id;

  INSERT INTO agregats
  SELECT
    `data`.road_segment_id,
    TUMBLE_START(`time`, INTERVAL '5' MINUTE),
    CAST(300 AS INT),
    `data`.provenance.run_id,
    TUMBLE_END(`time`, INTERVAL '5' MINUTE),
    MAX(`data`.intersection_id),
    MAX(`data`.provenance.source_type),
    COUNT(*),
    CAST(SUM(`data`.vehicle_count) AS BIGINT),
    ROUND(SUM(`data`.vehicle_count) * 60.0 / 300, 3),
    ROUND(SUM(`data`.average_speed_kmh * `data`.vehicle_count) / NULLIF(SUM(CASE WHEN `data`.average_speed_kmh IS NULL THEN 0 ELSE `data`.vehicle_count END), 0), 3),
    ROUND(AVG(`data`.occupancy_rate), 3),
    MAX(`data`.queue_length_m),
    SUM(CASE WHEN `data`.quality.status = 'VALID' THEN 0 ELSE 1 END)
  FROM mesures
  GROUP BY TUMBLE(`time`, INTERVAL '5' MINUTE), `data`.road_segment_id, `data`.provenance.run_id;
END;
