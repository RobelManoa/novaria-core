import { formatNumber, formatTime } from "./format";
import styles from "./TimeSeriesChart.module.css";

export interface ChartPoint {
  /** Début de fenêtre en millisecondes (UTC). */
  time: number;
  /** `null` : pas de valeur pour cette fenêtre, le trait est coupé. */
  value: number | null;
}

interface TimeSeriesChartProps {
  title: string;
  unit: string;
  points: readonly ChartPoint[];
  kind: "line" | "bar";
  /** Décimales affichées sur les axes et dans le tableau. */
  digits: number;
}

// Unités du viewBox, pas des pixels : 480 de large garde des libellés lisibles quand le SVG est réduit sur téléphone.
const WIDTH = 480;
const HEIGHT = 240;
const MARGIN = { top: 12, right: 12, bottom: 28, left: 44 };
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom;
const TICK_COUNT = 4;
/** Au-delà, les points ronds noieraient le trait : on ne garde que la ligne. */
const MAX_MARKERS = 60;

/** Mantisses des pas de graduation : l'axe avance par pas « ronds » (0,5 ; 1,5 ; 20 ; 25…). */
const STEPS = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];

/** Plus petit pas rond tel que `TICK_COUNT` pas depuis zéro contiennent `max`. */
function niceStep(max: number): number {
  if (max <= 0) return 0.25;
  const raw = max / TICK_COUNT;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const mantissa = STEPS.find((step) => step >= raw / magnitude - 1e-9) ?? 10;
  return mantissa * magnitude;
}

/** Nombre de décimales qu'il faut pour écrire les multiples de `step` sans les arrondir (au plus 2). */
function tickDigits(step: number): number {
  for (let digits = 0; digits < 2; digits += 1) {
    const scaled = step * 10 ** digits;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-9) return digits;
  }
  return 2;
}

/** Un tracé par suite de valeurs consécutives : une fenêtre sans valeur coupe le trait. */
function splitIntoRuns(
  points: readonly ChartPoint[],
  toXY: (point: ChartPoint, index: number) => [number, number],
): Array<{ key: number; coordinates: Array<[number, number]> }> {
  const runs: Array<{ key: number; coordinates: Array<[number, number]> }> = [];
  let open: (typeof runs)[number] | null = null;
  points.forEach((point, index) => {
    if (point.value === null) {
      open = null;
      return;
    }
    if (open === null) {
      open = { key: point.time, coordinates: [] };
      runs.push(open);
    }
    open.coordinates.push(toXY(point, index));
  });
  return runs;
}

function anchorOf(index: number, last: number): "start" | "middle" | "end" {
  if (index === 0) return "start";
  return index === last ? "end" : "middle";
}

function describe(points: readonly ChartPoint[], unit: string, digits: number): string {
  const values = points.flatMap((point) => (point.value === null ? [] : [point.value]));
  const first = points[0];
  const last = points.at(-1);
  if (values.length === 0 || !first || !last) return "aucune valeur";
  return (
    `de ${formatTime(first.time)} à ${formatTime(last.time)} UTC, ` +
    `minimum ${formatNumber(Math.min(...values), digits)} ${unit}, ` +
    `maximum ${formatNumber(Math.max(...values), digits)} ${unit}`
  );
}

/**
 * Graphique d'évolution en SVG. Aucune bibliothèque : l'échelle, les axes et le tracé tiennent ici, et
 * chaque valeur tracée est reprise telle quelle dans le tableau « Voir les valeurs » (texte équivalent
 * du graphique, lisible au clavier et par un lecteur d'écran).
 */
export default function TimeSeriesChart({
  title,
  unit,
  points,
  kind,
  digits,
}: Readonly<TimeSeriesChartProps>) {
  if (points.length === 0) return null;

  const values = points.flatMap((point) => (point.value === null ? [] : [point.value]));
  const step = niceStep(Math.max(0, ...values));
  const maximum = step * TICK_COUNT;
  const lastIndex = points.length - 1;
  // Courbe : premier point sur l'axe, dernier au bord droit. Barres : une bande par fenêtre, la barre en son centre,
  // pour qu'aucune ne déborde sur les graduations.
  const x = (index: number) => {
    if (kind === "bar") return MARGIN.left + ((index + 0.5) / points.length) * PLOT_WIDTH;
    return points.length === 1
      ? MARGIN.left + PLOT_WIDTH / 2
      : MARGIN.left + (index / lastIndex) * PLOT_WIDTH;
  };
  const y = (value: number) => MARGIN.top + PLOT_HEIGHT - (value / maximum) * PLOT_HEIGHT;
  const barWidth = Math.max(1, (PLOT_WIDTH / points.length) * 0.7);
  const runs = splitIntoRuns(points, (point, index) => [x(index), y(point.value as number)]);
  const ticks = Array.from({ length: TICK_COUNT + 1 }, (_, i) => step * i);
  const labelIndexes = [...new Set([0, Math.floor(lastIndex / 2), lastIndex])];

  return (
    <figure className={styles.figure}>
      <figcaption className={styles.title}>
        {title} <span className={styles.unit}>({unit})</span>
      </figcaption>
      <svg
        className={styles.svg}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${title} : ${describe(points, unit, digits)}`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              className={styles.grid}
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              className={styles.axis}
              x={MARGIN.left - 6}
              y={y(tick)}
              textAnchor="end"
              dy="0.32em"
            >
              {formatNumber(tick, tickDigits(step))}
            </text>
          </g>
        ))}
        {labelIndexes.map((index) => (
          <text
            key={points[index].time}
            className={styles.axis}
            x={x(index)}
            y={HEIGHT - 8}
            textAnchor={anchorOf(index, lastIndex)}
          >
            {formatTime(points[index].time)}
          </text>
        ))}
        {kind === "bar" &&
          points.map((point, index) =>
            point.value === null ? null : (
              <rect
                key={point.time}
                className={styles.bar}
                x={x(index) - barWidth / 2}
                y={y(point.value)}
                width={barWidth}
                height={MARGIN.top + PLOT_HEIGHT - y(point.value)}
              />
            ),
          )}
        {kind === "line" &&
          runs.map((run) =>
            run.coordinates.length > 1 ? (
              <polyline
                key={run.key}
                className={styles.line}
                points={run.coordinates.map(([px, py]) => `${px},${py}`).join(" ")}
              />
            ) : null,
          )}
        {kind === "line" &&
          points.length <= MAX_MARKERS &&
          points.map((point, index) =>
            point.value === null ? null : (
              <circle
                key={point.time}
                className={styles.marker}
                cx={x(index)}
                cy={y(point.value)}
                r={3}
              />
            ),
          )}
      </svg>
      <details className={styles.details}>
        <summary>Voir les valeurs</summary>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption className={styles.caption}>
              {title}, une ligne par fenêtre ({unit})
            </caption>
            <thead>
              <tr>
                <th scope="col">Début de fenêtre (UTC)</th>
                <th scope="col">{title}</th>
              </tr>
            </thead>
            <tbody>
              {points.map((point) => (
                <tr key={point.time}>
                  <th scope="row">{formatTime(point.time)}</th>
                  <td>{formatNumber(point.value, digits)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
