import { usePolling } from "@/hooks/usePolling";
import { listLatestIndicators, type Indicator } from "@/services/traitement";

export const INDICATORS_REFRESH_MS = 15_000;

const NONE: Indicator[] = [];

async function load(): Promise<Indicator[]> {
  return (await listLatestIndicators()).items;
}

/** Dernier indicateur de chaque tronçon, relu toutes les 15 s (le traitement n'a pas de flux). */
export function useLatestIndicators(refreshMs: number = INDICATORS_REFRESH_MS) {
  const { data, ...rest } = usePolling(load, refreshMs);
  return { indicators: data ?? NONE, ...rest };
}
