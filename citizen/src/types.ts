/**
 * Ce que l'API publique de congestion renvoie (`GET /api/v1/public/congestion`).
 * Contrat : `contracts/openapi/traitement.openapi.yaml`, schéma `PublicSegmentState` (ADR-030, section 4.4).
 * Six champs, aucun autre : l'application ne lit rien d'autre et un test compare ces valeurs au contrat.
 */
export const STATES = ["UNKNOWN", "FREE_FLOW", "SLOW", "CONGESTED"] as const;
export type CongestionState = (typeof STATES)[number];

export const APPROACHES = ["N", "E", "S", "W"] as const;
export type Approach = (typeof APPROACHES)[number];

export interface SegmentState {
  road_segment_id: string;
  intersection_id: string;
  approach: Approach;
  state: CongestionState;
  /** Fin de la dernière fenêtre d'une minute, en UTC (`...Z`). */
  updated_at: string;
  /** Vrai quand la donnée vient du simulateur (ADR-027) : toujours dit à l'écran. */
  simulated: boolean;
}

/**
 * Ce que l'API publique d'alertes renvoie (`GET /api/v1/public/alerts`).
 * Contrat : `contracts/openapi/alerte.openapi.yaml`, schéma `PublicAlert` (ADR-030, section 4.4).
 * Six champs, aucun autre : ni cause, ni règle, ni nom d'opérateur.
 */
export const SEVERITIES = ["INFO", "WARNING", "CRITICAL"] as const;
export type Severity = (typeof SEVERITIES)[number];

export interface PublicAlert {
  alert_id: string;
  road_segment_id: string;
  intersection_id: string;
  severity: Severity;
  /** Ouverture de l'alerte, en UTC (`...Z`). */
  opened_at: string;
  /** Vrai quand la donnée vient du simulateur (ADR-027) : toujours dit à l'écran. */
  simulated: boolean;
}
