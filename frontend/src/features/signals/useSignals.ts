import { usePolling } from "@/hooks/usePolling";
import { listSignals, type SignalState } from "@/services/reponse";

/** L'état des feux est calculé à la demande : le service n'a pas de flux, la page le relit à intervalle fixe. */
export const SIGNALS_REFRESH_MS = 3_000;

const NONE: SignalState[] = [];

async function load(): Promise<SignalState[]> {
  return (await listSignals()).items;
}

/** États des carrefours à feux, relus toutes les `SIGNALS_REFRESH_MS` (voir `usePolling`). */
export function useSignals(refreshMs: number = SIGNALS_REFRESH_MS) {
  const { data, ...rest } = usePolling(load, refreshMs);
  return { signals: data ?? NONE, ...rest };
}
