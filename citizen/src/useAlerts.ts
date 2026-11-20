import type { ApiError } from "./api";
import { fetchAlerts } from "./api";
import type { PublicAlert } from "./types";
import { usePolling } from "./usePolling";

/**
 * Les alertes sont relues toutes les 5 secondes, sans cache navigateur (voir `api.ts`) : une alerte créée par le service est
 * donc visible au plus 5 secondes plus tard (plus le temps de la requête), pour un critère de 10 secondes (CIT-05).
 * 0,2 requête par seconde et par visiteur : la limite de la passerelle est de 2 par seconde.
 */
export const ALERTS_REFRESH_MS = 5_000;

export interface AlertsView {
  status: "loading" | "ready" | "error";
  alerts: PublicAlert[];
  error: ApiError | null;
  lastSuccess: number | null;
  refreshing: boolean;
  refresh: () => void;
}

interface Options {
  fetcher?: (signal: AbortSignal) => Promise<PublicAlert[]>;
  intervalMs?: number;
  now?: () => number;
}

export function useAlerts({
  fetcher = (signal) => fetchAlerts(signal),
  intervalMs = ALERTS_REFRESH_MS,
  now = Date.now,
}: Options = {}): AlertsView {
  const view = usePolling<PublicAlert[]>({ fetcher, intervalMs, now });
  return { ...view, alerts: view.data ?? [] };
}
