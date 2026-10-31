import type { CongestionState, SourceType } from "@/services/traitement";

export const STATE_LABELS: Record<CongestionState, string> = {
  CONGESTED: "Congestionné",
  SLOW: "Ralenti",
  FREE_FLOW: "Fluide",
  UNKNOWN: "Inconnu",
};

/** L'origine des données est toujours dite : une donnée simulée ne se présente jamais comme réelle. */
export const SOURCE_LABELS: Record<SourceType, string> = {
  SIMULATED: "Données simulées",
  REAL_HISTORICAL: "Données réelles (historique)",
  REAL_LIVE: "Données réelles (en direct)",
};
