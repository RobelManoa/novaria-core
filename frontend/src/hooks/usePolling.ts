import { useCallback, useEffect, useRef, useState } from "react";

export type PollingPhase =
  { status: "loading" } | { status: "error"; error: unknown } | { status: "ready" };

/**
 * Relit une ressource à intervalle fixe, pour les services qui n'ont pas de flux. Un échec de relecture
 * garde les dernières valeurs et le signale (`stale`) ; seul un premier échec met la phase en erreur.
 * `retry` repart de « chargement ». `load` peut changer à chaque rendu : seul `refreshMs` relance la boucle.
 */
export function usePolling<T>(load: () => Promise<T>, refreshMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [phase, setPhase] = useState<PollingPhase>({ status: "loading" });
  const [stale, setStale] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [attempt, setAttempt] = useState(0);
  const loaded = useRef(false);
  const latestLoad = useRef(load);

  useEffect(() => {
    latestLoad.current = load;
  });

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const value = await latestLoad.current();
      loaded.current = true;
      setData(value);
      setStale(false);
      setUpdatedAt(Date.now());
      setPhase({ status: "ready" });
    } catch (error: unknown) {
      if (loaded.current) setStale(true);
      else setPhase({ status: "error", error });
    }
  }, []);

  useEffect(() => {
    let current = true;
    const tick = () => {
      if (current) void refresh();
    };
    tick();
    const timer = setInterval(tick, refreshMs);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [refresh, refreshMs, attempt]);

  const retry = useCallback(() => {
    loaded.current = false;
    setPhase({ status: "loading" });
    setAttempt((count) => count + 1);
  }, []);

  return { data, phase, stale, updatedAt, refresh, retry };
}
