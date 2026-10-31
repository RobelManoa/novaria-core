-- KPI-04 · Alertes par jour et par type.
-- Source : alertes.alert (une alerte par épisode, ADR-028 ; jamais une alerte par mesure).
-- Calcul : nombre d'alertes ouvertes le jour UTC de opened_at, dont celles résolues (état RESOLVED) et celles qui ne le sont pas.
-- Ce nombre ne dit pas combien d'alertes étaient justifiées : les fausses alertes demandent la vérité terrain du générateur (IA-03).
-- Fiche : docs/03-donnees/kpi.md.

CREATE VIEW dwh.kpi_alertes_par_jour AS
SELECT a.run_id,
       a.source_type,
       (a.opened_at AT TIME ZONE 'UTC')::date AS jour,
       a.kind,
       count(*) AS alertes,
       count(*) FILTER (WHERE a.state = 'RESOLVED') AS resolues,
       count(*) FILTER (WHERE a.state <> 'RESOLVED') AS non_resolues
FROM alertes.alert a
GROUP BY a.run_id, a.source_type, (a.opened_at AT TIME ZONE 'UTC')::date, a.kind;

COMMENT ON VIEW dwh.kpi_alertes_par_jour IS 'KPI-04 : alertes ouvertes par exécution, jour UTC et type (kind), avec le nombre de résolues et de non résolues.';
