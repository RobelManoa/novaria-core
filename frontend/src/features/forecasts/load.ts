import { toApiDateTime } from "@/features/dashboard/format";
import {
  listAllIndicators,
  listForecasts,
  type Forecast,
  type Indicator,
} from "@/services/traitement";

/** Horizons demandés (minutes) : un appel chacun, car l'API rend une prévision par tronçon et par horizon. */
export const HORIZONS = [5, 10, 15, 30, 45, 60] as const;
/** Horizon qui sert à découvrir les tronçons prévus. */
const DISCOVERY_HORIZON = 15;
/** Historique observé lu avant l'émission, en minutes. */
const LOOKBACK_MINUTES = 120;
const PAGE_SIZE = 500;
const MAX_PAGES = 3;
/** Nombre maximal d'indicateurs observés lus ; au-delà, la lecture s'arrête et la page le dit. */
export const MAX_OBSERVED = PAGE_SIZE * MAX_PAGES;

/** Tronçons pour lesquels l'API rend une prévision, du plus petit identifiant au plus grand. */
export async function loadSegments(): Promise<Forecast[]> {
  const { items } = await listForecasts({ horizon_min: DISCOVERY_HORIZON });
  return [...items].sort((a, b) => a.road_segment_id.localeCompare(b.road_segment_id));
}

export interface ForecastView {
  /** Une prévision par horizon rendu par l'API, pour le tronçon choisi. */
  forecasts: Forecast[];
  /** Indicateurs observés du même tronçon et du même run, du plus récent au plus ancien. */
  observed: Indicator[];
  truncated: boolean;
}

/**
 * Prévisions d'un tronçon à chaque horizon, et ce qui a été observé autour : de deux heures avant
 * l'émission jusqu'à la fin du dernier horizon. L'observé est celui du run de la prévision (sa provenance).
 */
export async function loadForecastView(
  segmentId: string,
  windowSizeS: 60 | 300,
): Promise<ForecastView> {
  const answers = await Promise.all(
    HORIZONS.map((horizon) =>
      listForecasts({ road_segment_id: [segmentId], horizon_min: horizon }),
    ),
  );
  const forecasts = answers
    .flatMap((answer) => answer.items)
    .filter((item) => item.road_segment_id === segmentId);
  if (forecasts.length === 0) return { forecasts: [], observed: [], truncated: false };

  const issued = Math.min(...forecasts.map((item) => Date.parse(item.issued_at)));
  const lastTarget = Math.max(...forecasts.map((item) => Date.parse(item.target_time)));
  const { items, truncated } = await listAllIndicators(
    {
      road_segment_id: segmentId,
      window_size_s: windowSizeS,
      run_id: forecasts[0].provenance.run_id,
      from: toApiDateTime(issued - LOOKBACK_MINUTES * 60_000),
      to: toApiDateTime(lastTarget + windowSizeS * 1000),
      limit: PAGE_SIZE,
    },
    MAX_PAGES,
  );
  return { forecasts, observed: items, truncated };
}
