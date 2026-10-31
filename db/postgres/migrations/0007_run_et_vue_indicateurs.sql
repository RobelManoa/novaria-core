-- 0007 · Exécutions (dwh.dim_run) et vue de lecture des indicateurs (dwh.v_indicator), BE-04.
-- L'API sert des indicateurs avec leur provenance complète (contrat OpenAPI, schéma Provenance) : une exécution simulée
-- doit dire son scénario et sa graine, un jeu historique son identifiant. Les faits ne gardent que run_id et source_type ;
-- le reste vit ici, une ligne par exécution, enregistrée par qui produit les faits (simulateur, chargeur ETL).

CREATE TABLE dwh.dim_run (
    run_id        text PRIMARY KEY CHECK (length(run_id) BETWEEN 1 AND 80),
    source_type   text NOT NULL REFERENCES dwh.dim_source (source_type),
    scenario_id   text CHECK (scenario_id ~ '^[a-z0-9_-]{1,60}$'),
    seed          bigint CHECK (seed >= 0),
    dataset_id    text CHECK (dataset_id ~ '^[a-z0-9_.-]{1,60}$'),
    registered_at timestamptz NOT NULL DEFAULT now(),
    -- Mêmes règles que le schéma Provenance du contrat : SIMULATED demande scénario et graine, REAL_HISTORICAL un jeu.
    CONSTRAINT dim_run_simulated_needs_scenario_and_seed CHECK (source_type <> 'SIMULATED' OR (scenario_id IS NOT NULL AND seed IS NOT NULL)),
    CONSTRAINT dim_run_historical_needs_dataset CHECK (source_type <> 'REAL_HISTORICAL' OR dataset_id IS NOT NULL)
);
COMMENT ON TABLE dwh.dim_run IS 'Exécutions qui produisent des faits : provenance complète (ADR-027). Une exécution non enregistrée ici n''apparaît pas dans l''API.';
COMMENT ON COLUMN dwh.dim_run.run_id IS '« live », identifiant d''un run du simulateur ou d''un jeu historique : celui des faits.';
COMMENT ON COLUMN dwh.dim_run.scenario_id IS 'Scénario du simulateur ; obligatoire si SIMULATED.';
COMMENT ON COLUMN dwh.dim_run.seed IS 'Graine du simulateur : rend le run reproductible ; obligatoire si SIMULATED.';
COMMENT ON COLUMN dwh.dim_run.dataset_id IS 'Jeu historique d''origine ; obligatoire si REAL_HISTORICAL.';

-- Lecture seule pour l'API : un indicateur = un tronçon, une fenêtre, une exécution (ADR-014, séparation écriture et lecture).
-- Le lien avec dim_run exige la même source_type : une exécution dont le type diffère de celui de ses faits n'est pas servie.
CREATE VIEW dwh.v_indicator AS
SELECT f.run_id || ':' || s.road_segment_id || ':' || f.window_size_s || ':' || (extract(epoch FROM f.window_start) * 1000)::bigint AS indicator_id,
       s.road_segment_id,
       i.intersection_id,
       f.window_start,
       f.window_size_s,
       f.vehicle_count,
       f.flow_veh_per_min,
       f.average_speed_kmh,
       f.occupancy_rate,
       f.max_queue_length_m,
       f.speed_ratio,
       f.sample_count,
       f.expected_sample_count,
       f.completeness,
       f.congestion_state,
       f.classifier_version,
       f.run_id,
       r.source_type,
       r.scenario_id,
       r.seed,
       r.dataset_id
FROM dwh.fact_traffic_window f
JOIN dwh.dim_road_segment s ON s.road_segment_key = f.road_segment_key
JOIN dwh.dim_intersection i ON i.intersection_key = s.intersection_key
JOIN dwh.dim_run r ON r.run_id = f.run_id AND r.source_type = f.source_type;
COMMENT ON VIEW dwh.v_indicator IS 'Indicateurs par fenêtre, avec provenance, tels que l''API les sert (BE-04). indicator_id = run_id:tronçon:taille:début en millisecondes depuis 1970, égal à l''id de l''événement.';
