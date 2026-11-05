-- 0008 · Provenance complète des alertes (MS-11).
-- La table `alertes.alert` ne gardait que `run_id` et `source_type`, alors que l'événement
-- `novaria.alert.state_changed.v1` et l'API exigent la provenance entière : `scenario_id` et `seed` pour une
-- donnée SIMULATED, `dataset_id` pour un jeu historique (ADR-027). Sans ces colonnes, une alerte relue dans la
-- base ne pourrait plus rebâtir son événement. Ajout seulement : aucune ligne existante ne change.
-- La base ne contrôle pas le lien entre `source_type` et ces colonnes (des lignes d'essai du contrôle des KPI
-- n'ont pas de scénario) : c'est le service d'alerte qui le garantit, en validant chaque événement avant écriture.

ALTER TABLE alertes.alert
    ADD COLUMN scenario_id text CHECK (scenario_id ~ '^[a-z0-9_-]{1,60}$'),
    ADD COLUMN seed        integer CHECK (seed >= 0),
    ADD COLUMN dataset_id  text CHECK (dataset_id ~ '^[a-z0-9_.-]{1,60}$');

COMMENT ON COLUMN alertes.alert.scenario_id IS 'Scénario du simulateur (provenance SIMULATED) : recopié de l''indicateur qui a ouvert l''alerte.';
COMMENT ON COLUMN alertes.alert.seed IS 'Graine du run (provenance SIMULATED).';
COMMENT ON COLUMN alertes.alert.dataset_id IS 'Jeu historique (provenance REAL_HISTORICAL).';
