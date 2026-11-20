import { useEffect, useState } from "react";

/** L'heure courante, remise à jour toutes les 30 secondes : « il y a 3 min » reste juste sans nouvel appel. */
export function useNow(intervalMs = 30_000, now: () => number = Date.now): number {
  const [current, setCurrent] = useState(now);
  useEffect(() => {
    const timer = window.setInterval(() => setCurrent(now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs, now]);
  return current;
}
