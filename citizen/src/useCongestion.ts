import type { ApiError } from "./api";
import { fetchCongestion } from "./api";
import type { SegmentState } from "./types";
import { usePolling } from "./usePolling";

export const REFRESH_MS = 15_000;

export interface CongestionView {
  status: "loading" | "ready" | "error";
  segments: SegmentState[];
  error: ApiError | null;
  lastSuccess: number | null;
  refreshing: boolean;
  refresh: () => void;
}

interface Options {
  fetcher?: (signal: AbortSignal) => Promise<SegmentState[]>;
  intervalMs?: number;
  now?: () => number;
}

/** L'état de la circulation, relu toutes les 15 secondes (la passerelle garde une réponse 5 secondes). */
export function useCongestion({
  fetcher = (signal) => fetchCongestion(signal),
  intervalMs = REFRESH_MS,
  now = Date.now,
}: Options = {}): CongestionView {
  const view = usePolling<SegmentState[]>({ fetcher, intervalMs, now });
  return { ...view, segments: view.data ?? [] };
}
