import type { Forecast, Indicator } from "@/services/traitement";

/** Une prévision et, quand son instant est déjà passé, la valeur observée à cet instant. */
export interface ComparisonRow {
  horizonMin: number;
  /** Instant prévu, en millisecondes depuis 1970 (UTC). */
  targetTime: number;
  predictedRatio: number;
  predictedState: Forecast["predicted_state"];
  /** Ratio de vitesse de la fenêtre qui contient l'instant prévu ; `null` tant qu'il n'est pas observé. */
  observedRatio: number | null;
  /** Prévu moins observé. */
  difference: number | null;
}

/** Trois décimales comme l'API ; l'addition de zéro évite l'affichage « -0 ». */
function roundedDifference(predicted: number, observed: number): number {
  return Math.round((predicted - observed) * 1000) / 1000 + 0;
}

/** Ratio observé dans la fenêtre `[début, début + taille[` qui contient `time`, s'il existe et s'il a une vitesse. */
function observedAt(time: number, observed: readonly Indicator[]): number | null {
  const window = observed.find((item) => {
    const start = Date.parse(item.window_start);
    return start <= time && time < start + item.window_size_s * 1000;
  });
  return window?.speed_ratio ?? null;
}

/**
 * Une ligne par prévision, de l'horizon le plus court au plus long. L'écart n'existe que si l'instant
 * prévu a déjà été observé : on ne compare jamais une prévision à une valeur absente ou supposée.
 */
export function compareForecasts(
  forecasts: readonly Forecast[],
  observed: readonly Indicator[],
): ComparisonRow[] {
  return [...forecasts]
    .sort((a, b) => a.horizon_min - b.horizon_min)
    .map((item) => {
      const targetTime = Date.parse(item.target_time);
      const observedRatio = observedAt(targetTime, observed);
      return {
        horizonMin: item.horizon_min,
        targetTime,
        predictedRatio: item.predicted_speed_ratio,
        predictedState: item.predicted_state,
        observedRatio,
        difference:
          observedRatio === null
            ? null
            : roundedDifference(item.predicted_speed_ratio, observedRatio),
      };
    });
}
