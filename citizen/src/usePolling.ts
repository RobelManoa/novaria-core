import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export interface PollingView<T> {
  /** `loading` : aucune réponse encore ; `ready` : des données (éventuellement anciennes) ; `error` : rien à montrer. */
  status: "loading" | "ready" | "error";
  data: T | null;
  /** La dernière erreur, tant qu'elle n'a pas été suivie d'un succès. */
  error: ApiError | null;
  /** Instant (ms) du dernier succès : sert à dire « il y a 3 min ». */
  lastSuccess: number | null;
  refreshing: boolean;
  refresh: () => void;
}

export interface PollingOptions<T> {
  fetcher: (signal: AbortSignal) => Promise<T>;
  intervalMs: number;
  now?: () => number;
}

/**
 * Lit une route publique, puis la relit à intervalle fixe.
 * Une erreur n'efface jamais les dernières données : l'écran les garde en disant qu'elles sont anciennes.
 * Rien n'est relu tant que la page est cachée ; au retour de l'onglet, une lecture a lieu tout de suite.
 */
export function usePolling<T>({
  fetcher,
  intervalMs,
  now = Date.now,
}: PollingOptions<T>): PollingView<T> {
  const [data, setData] = useState<T | null>(null);
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
      const result = await fetcherRef.current(mine.signal);
      if (mine.signal.aborted) return;
      setData(result);
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

  const status = data !== null ? "ready" : error !== null ? "error" : "loading";
  return { status, data, error, lastSuccess, refreshing, refresh: () => void load() };
}
