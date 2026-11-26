import type { SpeedForecastList } from "@/services/traitement";

type Item = SpeedForecastList["items"][number];

/** Horizons du modèle entraîné (minutes) : cinq sorties, de 5 à 30 minutes. */
export const TRAINED_HORIZONS = [5, 10, 15, 20, 25, 30] as const;

export interface Scores {
  /** Capteurs dont la vitesse réelle est connue à l'instant prévu. */
  compared: number;
  modelMae: number;
  persistenceMae: number;
  /** Part des capteurs où le modèle est plus proche du réel que la persistance. */
  modelWins: number;
}

/**
 * L'erreur moyenne (km/h) du modèle et de la persistance, sur les capteurs dont l'observé est déjà dans l'entrepôt.
 * Null quand rien n'est comparable : on n'invente pas un score.
 */
export function scoreForecasts(items: readonly Item[]): Scores | null {
  const known = items.filter(
    (item): item is Item & { observed_speed_kmh: number } => item.observed_speed_kmh !== null,
  );
  if (known.length === 0) return null;
  const mean = (values: number[]) => values.reduce((a, b) => a + b, 0) / values.length;
  const modelErrors = known.map((i) => Math.abs(i.predicted_speed_kmh - i.observed_speed_kmh));
  const persistenceErrors = known.map((i) =>
    Math.abs(i.persistence_speed_kmh - i.observed_speed_kmh),
  );
  const wins = modelErrors.filter((error, i) => error < (persistenceErrors[i] ?? Infinity)).length;
  return {
    compared: known.length,
    modelMae: mean(modelErrors),
    persistenceMae: mean(persistenceErrors),
    modelWins: wins / known.length,
  };
}

export interface SensorRow {
  sensorId: string;
  predicted: number;
  persistence: number;
  observed: number | null;
  modelError: number | null;
  persistenceError: number | null;
}

/** Les capteurs où le modèle et la persistance s'écartent le plus de l'observé, puis ceux sans observé. */
export function worstSensors(items: readonly Item[], limit: number): SensorRow[] {
  const rows = items.map<SensorRow>((i) => ({
    sensorId: i.sensor_id,
    predicted: i.predicted_speed_kmh,
    persistence: i.persistence_speed_kmh,
    observed: i.observed_speed_kmh,
    modelError:
      i.observed_speed_kmh === null ? null : Math.abs(i.predicted_speed_kmh - i.observed_speed_kmh),
    persistenceError:
      i.observed_speed_kmh === null
        ? null
        : Math.abs(i.persistence_speed_kmh - i.observed_speed_kmh),
  }));
  const withObserved = rows
    .filter((row) => row.persistenceError !== null)
    .sort((a, b) => (b.persistenceError ?? 0) - (a.persistenceError ?? 0));
  return [...withObserved, ...rows.filter((row) => row.persistenceError === null)].slice(0, limit);
}

/** Une date ISO (UTC) pour un champ `datetime-local` (minutes, sans fuseau) et retour. */
export const toInputValue = (iso: string) => iso.slice(0, 16);
export const fromInputValue = (value: string) => `${value}:00Z`;

/**
 * L'instant proposé à l'ouverture : une heure avant la fin des mesures, pour que l'avenir à 30 minutes soit déjà dans l'entrepôt
 * et que la comparaison avec l'observé soit possible dès l'arrivée sur la page.
 */
export function defaultAsOf(last: string): string {
  return new Date(Date.parse(last) - 60 * 60_000).toISOString().replace(".000Z", "Z");
}
