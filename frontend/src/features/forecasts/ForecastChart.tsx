import chart from "@/features/dashboard/TimeSeriesChart.module.css";
import { niceStep, TICK_COUNT, tickDigits } from "@/features/dashboard/axis";
import { formatNumber, formatTime } from "@/features/dashboard/format";
import styles from "./ForecastChart.module.css";

export interface SeriesPoint {
  /** Instant en millisecondes (UTC). */
  time: number;
  /** `null` : pas de valeur à cet instant, le trait est coupé. */
  value: number | null;
}

interface ForecastChartProps {
  observed: readonly SeriesPoint[];
  predicted: readonly SeriesPoint[];
  /** Instant d'émission des prévisions : ce qui précède est du passé. */
  issuedAt: number;
}

const WIDTH = 480;
const HEIGHT = 260;
const MARGIN = { top: 16, right: 12, bottom: 28, left: 44 };
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom;
/** Au-delà, les points ronds noieraient la courbe observée. */
const MAX_MARKERS = 60;
/** Distance minimale (unités du viewBox) entre deux libellés de l'axe du temps. */
const MIN_LABEL_GAP = 64;
const DIGITS = 3;

function runsOf(
  points: readonly SeriesPoint[],
  toXY: (point: SeriesPoint) => [number, number],
): Array<{ key: number; coordinates: Array<[number, number]> }> {
  const runs: Array<{ key: number; coordinates: Array<[number, number]> }> = [];
  let open: (typeof runs)[number] | null = null;
  for (const point of points) {
    if (point.value === null) {
      open = null;
      continue;
    }
    if (open === null) {
      open = { key: point.time, coordinates: [] };
      runs.push(open);
    }
    open.coordinates.push(toXY(point));
  }
  return runs;
}

function anchorOf(time: number, start: number, end: number): "start" | "middle" | "end" {
  if (time === start) return "start";
  return time === end ? "end" : "middle";
}

const diamond = (x: number, y: number, radius = 5) =>
  `${x},${y - radius} ${x + radius},${y} ${x},${y + radius} ${x - radius},${y}`;

function summarize(observed: readonly SeriesPoint[], predicted: readonly SeriesPoint[]): string {
  const seen = observed.filter((point) => point.value !== null);
  const first = seen[0];
  const last = seen.at(-1);
  const past =
    first && last
      ? `observé de ${formatTime(first.time)} à ${formatTime(last.time)} UTC (${seen.length} valeurs)`
      : "aucune valeur observée";
  const future =
    predicted.length > 0
      ? `${predicted.length} valeurs prévues jusqu'à ${formatTime(predicted.at(-1)?.time ?? 0)} UTC`
      : "aucune valeur prévue";
  return `${past} ; ${future}`;
}

/** Instants (sans doublon) de l'axe et du tableau, du plus ancien au plus récent. */
function timesOf(...series: Array<readonly SeriesPoint[]>): number[] {
  return [...new Set(series.flatMap((points) => points.map((point) => point.time)))].sort(
    (a, b) => a - b,
  );
}

/**
 * Courbe observée (trait plein, ronds) et prévisions (pointillés, losanges) d'un tronçon : le ratio de vitesse
 * en fonction du temps réel. Les deux séries ont des pas différents (une fenêtre toutes les 1 ou 5 minutes,
 * horizons de 5 à 60 minutes) : l'axe est donc proportionnel au temps. Toute valeur tracée est reprise dans
 * le tableau « Voir les valeurs ».
 */
export default function ForecastChart({
  observed,
  predicted,
  issuedAt,
}: Readonly<ForecastChartProps>) {
  const times = timesOf(observed, predicted, [{ time: issuedAt, value: null }]);
  const start = times[0];
  const span = Math.max(times[times.length - 1] - start, 1);
  const values = [...observed, ...predicted].flatMap((point) =>
    point.value === null ? [] : [point.value],
  );
  const step = niceStep(Math.max(0, ...values));
  const maximum = step * TICK_COUNT;
  const x = (time: number) => MARGIN.left + ((time - start) / span) * PLOT_WIDTH;
  const y = (value: number) => MARGIN.top + PLOT_HEIGHT - (value / maximum) * PLOT_HEIGHT;
  const toXY = (point: SeriesPoint): [number, number] => [x(point.time), y(point.value as number)];
  const ticks = Array.from({ length: TICK_COUNT + 1 }, (_, i) => step * i);

  // Le premier libellé s'aligne sur l'axe, le dernier sur le bord droit : centrés, ils déborderaient du graphique.
  const end = times[times.length - 1];
  // Début et fin d'abord, l'émission ensuite : un libellé trop proche d'un libellé déjà gardé est omis.
  const labelTimes = [start, end, issuedAt].reduce<number[]>(
    (kept, time) =>
      kept.every((other) => Math.abs(x(time) - x(other)) >= MIN_LABEL_GAP) ? [...kept, time] : kept,
    [],
  );
  const observedRuns = runsOf(observed, toXY);
  const predictedRuns = runsOf(predicted, toXY);

  return (
    <figure className={chart.figure}>
      <figcaption className={chart.title}>
        Ratio de vitesse, observé et prévu{" "}
        <span className={chart.unit}>(vitesse ÷ vitesse fluide)</span>
      </figcaption>
      <ul className={styles.legend}>
        <li className={styles.legendItem}>
          <svg width="28" height="12" aria-hidden="true">
            <line x1="0" x2="28" y1="6" y2="6" className={chart.line} />
            <circle cx="14" cy="6" r="3" className={chart.marker} />
          </svg>
          Observé
        </li>
        <li className={styles.legendItem}>
          <svg width="28" height="12" aria-hidden="true">
            <line x1="0" x2="28" y1="6" y2="6" className={styles.predictedLine} />
            <polygon points={diamond(14, 6, 4)} className={styles.predictedMarker} />
          </svg>
          Prévu
        </li>
      </ul>
      <svg
        className={chart.svg}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Ratio de vitesse : ${summarize(observed, predicted)}`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              className={chart.grid}
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              className={chart.axis}
              x={MARGIN.left - 6}
              y={y(tick)}
              textAnchor="end"
              dy="0.32em"
            >
              {formatNumber(tick, tickDigits(step))}
            </text>
          </g>
        ))}
        {labelTimes.map((time) => (
          <text
            key={time}
            className={chart.axis}
            x={x(time)}
            y={HEIGHT - 8}
            textAnchor={anchorOf(time, start, end)}
          >
            {formatTime(time)}
          </text>
        ))}
        <line
          className={styles.issued}
          x1={x(issuedAt)}
          x2={x(issuedAt)}
          y1={MARGIN.top}
          y2={MARGIN.top + PLOT_HEIGHT}
        />
        <text className={chart.axis} x={x(issuedAt) + 4} y={MARGIN.top + 10}>
          Émission
        </text>
        {observedRuns.map((run) =>
          run.coordinates.length > 1 ? (
            <polyline
              key={run.key}
              className={chart.line}
              points={run.coordinates.map(([px, py]) => `${px},${py}`).join(" ")}
            />
          ) : null,
        )}
        {observed.length <= MAX_MARKERS &&
          observed.map((point) =>
            point.value === null ? null : (
              <circle
                key={point.time}
                className={chart.marker}
                cx={x(point.time)}
                cy={y(point.value)}
                r={3}
              />
            ),
          )}
        {predictedRuns.map((run) =>
          run.coordinates.length > 1 ? (
            <polyline
              key={run.key}
              className={styles.predictedLine}
              points={run.coordinates.map(([px, py]) => `${px},${py}`).join(" ")}
            />
          ) : null,
        )}
        {predicted.map((point) =>
          point.value === null ? null : (
            <polygon
              key={point.time}
              className={styles.predictedMarker}
              points={diamond(x(point.time), y(point.value))}
            />
          ),
        )}
      </svg>
      <details className={chart.details}>
        <summary>Voir les valeurs</summary>
        <div className={chart.tableWrap}>
          <table className={chart.table}>
            <caption className={chart.caption}>
              Ratio de vitesse observé et prévu, par instant
            </caption>
            <thead>
              <tr>
                <th scope="col">Instant (UTC)</th>
                <th scope="col">Observé</th>
                <th scope="col">Prévu</th>
              </tr>
            </thead>
            <tbody>
              {times.map((time) => (
                <tr key={time}>
                  <th scope="row">{formatTime(time)}</th>
                  <td>
                    {formatNumber(observed.find((p) => p.time === time)?.value ?? null, DIGITS)}
                  </td>
                  <td>
                    {formatNumber(predicted.find((p) => p.time === time)?.value ?? null, DIGITS)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
