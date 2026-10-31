import { formatDateTime, formatNumber } from "@/features/dashboard/format";
import { STATE_LABELS } from "@/features/dashboard/labels";
import type { ComparisonRow } from "./compare";
import styles from "./ComparisonTable.module.css";

interface ComparisonTableProps {
  rows: readonly ComparisonRow[];
  /** Fin de la dernière fenêtre observée, ou `null` sans aucune valeur observée. */
  observedUntil: number | null;
}

const DIGITS = 3;

/** Pourquoi il n'y a rien à comparer : l'instant n'est pas encore passé, ou aucune valeur n'existe. */
function missingObserved(row: ComparisonRow, observedUntil: number | null): string {
  return observedUntil !== null && row.targetTime >= observedUntil
    ? "Pas encore observé"
    : "Non disponible";
}

/** Une ligne par horizon : prévu, état prévu, observé à l'instant visé et écart. Valeurs brutes de l'API. */
export default function ComparisonTable({ rows, observedUntil }: Readonly<ComparisonTableProps>) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <caption className={styles.caption}>Prévu et observé, par horizon</caption>
        <thead>
          <tr>
            <th scope="col">Horizon (min)</th>
            <th scope="col">Instant prévu (UTC)</th>
            <th scope="col">Ratio prévu</th>
            <th scope="col">État prévu</th>
            <th scope="col">Ratio observé</th>
            <th scope="col">Écart (prévu − observé)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.horizonMin}>
              <th scope="row">{row.horizonMin}</th>
              <td>{formatDateTime(row.targetTime)}</td>
              <td className={styles.number}>{formatNumber(row.predictedRatio, DIGITS)}</td>
              <td>{row.predictedState ? STATE_LABELS[row.predictedState] : "—"}</td>
              {row.observedRatio === null ? (
                <td className={styles.muted} colSpan={2}>
                  {missingObserved(row, observedUntil)}
                </td>
              ) : (
                <>
                  <td className={styles.number}>{formatNumber(row.observedRatio, DIGITS)}</td>
                  <td className={styles.number}>{formatNumber(row.difference, DIGITS)}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
