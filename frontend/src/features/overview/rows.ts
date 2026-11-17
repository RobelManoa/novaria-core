import type { SignalState } from "@/services/reponse";
import type { CongestionState, Indicator } from "@/services/traitement";

export interface IntersectionRow {
  intersectionId: string;
  segmentCount: number;
  stateCounts: Record<CongestionState, number>;
  /** Moyenne des vitesses pondérée par le nombre de véhicules ; `null` sans véhicule. */
  speedKmh: number | null;
  /** Somme des débits des tronçons du carrefour. */
  flowVehPerMin: number;
  /** Les feux du carrefour ; `null` si le carrefour n'est pas piloté par le service de réponse. */
  signal: SignalState | null;
}

/**
 * Un carrefour par ligne, d'après le dernier indicateur de chaque tronçon (`latest`) et l'état des feux.
 * Les carrefours qui n'ont que des feux, sans indicateur, apparaissent aussi : on ne cache pas un feu.
 */
export function intersectionRows(latest: Indicator[], signals: SignalState[]): IntersectionRow[] {
  const ids = new Set([
    ...latest.map((item) => item.intersection_id),
    ...signals.map((item) => item.intersection_id),
  ]);
  return [...ids]
    .sort((a, b) => a.localeCompare(b))
    .map((intersectionId) => {
      const items = latest.filter((item) => item.intersection_id === intersectionId);
      const stateCounts: Record<CongestionState, number> = {
        CONGESTED: 0,
        SLOW: 0,
        FREE_FLOW: 0,
        UNKNOWN: 0,
      };
      for (const item of items) stateCounts[item.congestion_state] += 1;
      const withSpeed = items.filter((item) => item.average_speed_kmh !== null);
      const weight = withSpeed.reduce((sum, item) => sum + item.vehicle_count, 0);
      return {
        intersectionId,
        segmentCount: items.length,
        stateCounts,
        speedKmh:
          weight === 0
            ? null
            : withSpeed.reduce(
                (sum, item) => sum + (item.average_speed_kmh as number) * item.vehicle_count,
                0,
              ) / weight,
        flowVehPerMin: items.reduce((sum, item) => sum + item.flow_veh_per_min, 0),
        signal: signals.find((item) => item.intersection_id === intersectionId) ?? null,
      };
    });
}

/** Fin de la fenêtre la plus récente parmi les indicateurs, en millisecondes ; `null` sans indicateur. */
export function latestWindowEnd(latest: Indicator[]): number | null {
  if (latest.length === 0) return null;
  return Math.max(
    ...latest.map((item) => Date.parse(item.window_start) + item.window_size_s * 1000),
  );
}
