import type { CongestionState, Indicator } from "@/services/traitement";

/** Une fenêtre de temps du graphique : tous les tronçons du filtre réunis. */
export interface SeriesPoint {
  /** Début de la fenêtre, en millisecondes depuis 1970 (UTC). */
  time: number;
  /** Moyenne des vitesses des tronçons, pondérée par leur nombre de véhicules ; `null` sans véhicule. */
  speedKmh: number | null;
  /** Somme des débits des tronçons. */
  flowVehPerMin: number;
  /** Somme des véhicules comptés. */
  vehicleCount: number;
}

export interface Summary {
  indicatorCount: number;
  vehicleCount: number;
  averageSpeedKmh: number | null;
  averageFlowVehPerMin: number | null;
  segmentCount: number;
  /** Dernier indicateur de chaque tronçon, par identifiant de tronçon : valeurs brutes de l'API. */
  latest: Indicator[];
  /** Nombre de tronçons dans chaque état, d'après leur fenêtre la plus récente. */
  stateCounts: Record<CongestionState, number>;
  /** Une entrée par début de fenêtre, du plus ancien au plus récent. */
  series: SeriesPoint[];
}

/** Du plus grave au moins grave : l'ordre des cartes, du graphique et de la légende. */
export const STATES: readonly CongestionState[] = ["CONGESTED", "SLOW", "FREE_FLOW", "UNKNOWN"];

/** Moyenne de `values` pondérée par `weights` ; `null` si le poids total est nul. */
function weightedMean(values: number[], weights: number[]): number | null {
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
  if (totalWeight === 0) return null;
  return values.reduce((sum, value, index) => sum + value * weights[index], 0) / totalWeight;
}

function groupByWindow(indicators: Indicator[]): Map<number, Indicator[]> {
  const windows = new Map<number, Indicator[]>();
  for (const item of indicators) {
    const time = Date.parse(item.window_start);
    windows.set(time, [...(windows.get(time) ?? []), item]);
  }
  return windows;
}

function buildSeries(indicators: Indicator[]): SeriesPoint[] {
  return [...groupByWindow(indicators)]
    .sort(([first], [second]) => first - second)
    .map(([time, items]) => {
      const withSpeed = items.filter((item) => item.average_speed_kmh !== null);
      return {
        time,
        speedKmh: weightedMean(
          withSpeed.map((item) => item.average_speed_kmh as number),
          withSpeed.map((item) => item.vehicle_count),
        ),
        flowVehPerMin: items.reduce((sum, item) => sum + item.flow_veh_per_min, 0),
        vehicleCount: items.reduce((sum, item) => sum + item.vehicle_count, 0),
      };
    });
}

/** Dernier indicateur de chaque tronçon (celui dont la fenêtre commence le plus tard). */
function latestPerSegment(indicators: Indicator[]): Indicator[] {
  const latest = new Map<string, Indicator>();
  for (const item of indicators) {
    const known = latest.get(item.road_segment_id);
    if (!known || Date.parse(item.window_start) > Date.parse(known.window_start)) {
      latest.set(item.road_segment_id, item);
    }
  }
  return [...latest.values()].sort((a, b) => a.road_segment_id.localeCompare(b.road_segment_id));
}

/**
 * Valeurs des cartes et des graphiques. Tout se déduit des indicateurs reçus, sans autre source :
 * - vitesse moyenne : moyenne des `average_speed_kmh` pondérée par `vehicle_count`, comme le contrat
 *   définit la vitesse d'une fenêtre ; les fenêtres sans vitesse n'y entrent pas ;
 * - véhicules : somme des `vehicle_count` ;
 * - débit moyen : débit cumulé des tronçons (somme des `flow_veh_per_min` d'une fenêtre), moyenné sur les fenêtres ;
 * - états : `congestion_state` de la fenêtre la plus récente de chaque tronçon.
 */
export function summarize(indicators: Indicator[]): Summary {
  const series = buildSeries(indicators);
  const speed = indicators.filter((item) => item.average_speed_kmh !== null);
  const stateCounts: Record<CongestionState, number> = {
    CONGESTED: 0,
    SLOW: 0,
    FREE_FLOW: 0,
    UNKNOWN: 0,
  };
  const latest = latestPerSegment(indicators);
  for (const item of latest) stateCounts[item.congestion_state] += 1;

  return {
    indicatorCount: indicators.length,
    vehicleCount: indicators.reduce((sum, item) => sum + item.vehicle_count, 0),
    averageSpeedKmh: weightedMean(
      speed.map((item) => item.average_speed_kmh as number),
      speed.map((item) => item.vehicle_count),
    ),
    averageFlowVehPerMin:
      series.length === 0
        ? null
        : series.reduce((sum, point) => sum + point.flowVehPerMin, 0) / series.length,
    segmentCount: latest.length,
    latest,
    stateCounts,
    series,
  };
}
