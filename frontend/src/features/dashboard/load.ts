import { listAllIndicators, listIndicators, type Indicator } from "@/services/traitement";
import type { Filters } from "./filters";
import { toApiDateTime } from "./format";

/** Une page d'indicateurs : le maximum du contrat. */
export const PAGE_SIZE = 500;
/** 10 pages de 500 : au-delà, la lecture s'arrête et l'écran le dit. */
export const MAX_PAGES = 10;

export interface DashboardData {
  indicators: Indicator[];
  /** Vrai si la limite de pages a coupé la lecture : les fenêtres les plus anciennes manquent. */
  truncated: boolean;
  /** Origine des données (simulées, historiques, en direct), lue sur l'indicateur le plus récent. */
  provenance: Indicator["provenance"] | null;
}

/**
 * Lit les indicateurs du filtre. La période se termine à la fin de la dernière fenêtre disponible, pas à
 * l'heure actuelle : un jeu simulé ou historique ne serait sinon jamais dans la période. Le run est celui
 * de cette dernière fenêtre (comme `/indicators/latest`), pour ne pas additionner deux exécutions.
 */
export async function loadDashboard(filters: Filters): Promise<DashboardData> {
  const zone = filters.intersectionId ? { intersection_id: filters.intersectionId } : {};
  const newest = await listIndicators({ ...zone, window_size_s: filters.windowSizeS, limit: 1 });
  const last = newest.items[0];
  if (!last) return { indicators: [], truncated: false, provenance: null };

  const end = Date.parse(last.window_start) + last.window_size_s * 1000;
  const start = end - filters.periodHours * 3_600_000;
  const { items, truncated } = await listAllIndicators(
    {
      ...zone,
      window_size_s: filters.windowSizeS,
      run_id: last.provenance.run_id,
      from: toApiDateTime(start),
      to: toApiDateTime(end),
      limit: PAGE_SIZE,
    },
    MAX_PAGES,
  );
  return { indicators: items, truncated, provenance: last.provenance };
}
