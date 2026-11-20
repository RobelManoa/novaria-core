import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchCongestion } from "./api";
import type { SegmentState } from "./types";

export const REFRESH_MS = 15_000;

export interface CongestionView {
  /** `loading` : aucune réponse encore ; `ready` : des données (éventuellement anciennes) ; `error` : rien à montrer. */
  status: "loading" | "ready" | "error";
  segments: SegmentState[];
  /** La dernière erreur, tant qu'elle n'a pas été suivie d'un succès. */
  error: ApiError | null;
  /** Instant (ms) du dernier succès : sert à dire « il y a 3 min ». */
  lastSuccess: number | null;
  refreshing: boolean;
  refresh: () => void;
}

interface Options {
  fetcher?: (signal: AbortSignal) => Promise<SegmentState[]>;
  intervalMs?: number;
  now?: () => number;
}

/**
 * Lit l'état de la circulation, puis le relit toutes les 15 secondes (la passerelle garde une réponse 5 secondes).
 * Une erreur n'efface jamais les dernières données : l'écran les garde en disant qu'elles sont anciennes.
 * Rien n'est relu tant que la page est cachée.
 */
export function useCongestion({
  fetcher = (signal) => fetchCongestion(signal),
  intervalMs = REFRESH_MS,
  now = Date.now,
}: Options = {}): CongestionView {
  const [segments, setSegments] = useState<SegmentState[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [lastSuccess, setLastSuccess] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(true);
  const controller = useRef<AbortController | null>(null);
  const fetcherRef = useRef(fetcher);
  const nowRef = useRef(now);
  fetcherRef.current = fetcher;
  nowRef.current = now;

  const load = useCallback(async () => {
    controller.current?.abort();
    const mine = new AbortController();
    controller.current = mine;
    setRefreshing(true);
    try {
      const items = await fetcherRef.current(mine.signal);
      if (mine.signal.aborted) return;
      setSegments(items);
      setError(null);
      setLastSuccess(nowRef.current());
    } catch (caught) {
      if (mine.signal.aborted) return;
      setError(
        caught instanceof ApiError ? caught : new ApiError("inattendue", "Erreur inattendue."),
      );
    } finally {
      if (controller.current === mine) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, intervalMs);
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      controller.current?.abort();
    };
  }, [load, intervalMs]);

  const status = segments !== null ? "ready" : error !== null ? "error" : "loading";
  return {
    status,
    segments: segments ?? [],
    error,
    lastSuccess,
    refreshing,
    refresh: () => void load(),
  };
}
