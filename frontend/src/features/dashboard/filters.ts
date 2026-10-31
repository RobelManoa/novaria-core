/** Périodes proposées : durée avant la fin de la dernière fenêtre de données (voir `loadDashboard`). */
export const PERIODS = [
  { hours: 1, label: "Dernière heure" },
  { hours: 6, label: "6 dernières heures" },
  { hours: 24, label: "24 dernières heures" },
] as const;

/** Tailles de fenêtre du contrat (`WindowSize`). */
export const WINDOW_SIZES = [
  { seconds: 60, label: "1 minute" },
  { seconds: 300, label: "5 minutes" },
] as const;

export type WindowSizeSeconds = (typeof WINDOW_SIZES)[number]["seconds"];

export interface Filters {
  periodHours: number;
  windowSizeS: WindowSizeSeconds;
  /** Zone : un carrefour (`INT_01`), ou `null` pour tout le réseau. */
  intersectionId: string | null;
}

/** Fenêtres d'une minute : c'est le défaut de l'API, et celles dont l'état déclenche les alertes. */
export const DEFAULT_FILTERS: Filters = { periodHours: 1, windowSizeS: 60, intersectionId: null };
