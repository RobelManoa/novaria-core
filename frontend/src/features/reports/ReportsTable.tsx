import { formatDateTime } from "@/features/dashboard/format";
import type { Report } from "@/services/traitement";
import { formatFileSize, shortHash } from "./format";
import styles from "./ReportsTable.module.css";

interface ReportsTableProps {
  reports: readonly Report[];
  /** Identifiant du rapport en cours de téléchargement ; son bouton est alors désactivé. */
  downloadingId: string | null;
  onDownload: (report: Report) => void;
}

/**
 * Un rapport par ligne, dans l'ordre reçu de l'API (du plus récent au plus ancien). Valeurs brutes du
 * contrat. Sur un écran étroit, chaque ligne devient une carte (`data-label` donne l'intitulé de chaque
 * valeur) ; les rôles ARIA sont explicites car `display: block` retire la sémantique de tableau.
 */
export default function ReportsTable({
  reports,
  downloadingId,
  onDownload,
}: Readonly<ReportsTableProps>) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table} role="table">
        <caption className={styles.caption}>Rapports générés par le robot</caption>
        <thead role="rowgroup">
          <tr role="row">
            <th scope="col" role="columnheader">
              Rapport
            </th>
            <th scope="col" role="columnheader">
              Période couverte (UTC)
            </th>
            <th scope="col" role="columnheader">
              Généré le (UTC)
            </th>
            <th scope="col" role="columnheader" className={styles.number}>
              Taille
            </th>
            <th scope="col" role="columnheader">
              Empreinte SHA-256
            </th>
            <th scope="col" role="columnheader" className={styles.action}>
              Téléchargement
            </th>
          </tr>
        </thead>
        <tbody role="rowgroup">
          {reports.map((report) => (
            <tr key={report.report_id} role="row">
              <th scope="row" role="rowheader">
                <span className={styles.title}>
                  {report.title}
                  <span className={styles.file}>{report.file_name}</span>
                </span>
              </th>
              <td role="cell" data-label="Période couverte (UTC)" className={styles.nowrap}>
                <span className={styles.block}>
                  {`du ${formatDateTime(Date.parse(report.period_start))}`}
                </span>{" "}
                <span className={styles.block}>
                  {`au ${formatDateTime(Date.parse(report.period_end))}`}
                </span>
              </td>
              <td role="cell" data-label="Généré le (UTC)" className={styles.nowrap}>
                {formatDateTime(Date.parse(report.generated_at))}
              </td>
              <td role="cell" data-label="Taille" className={`${styles.nowrap} ${styles.number}`}>
                {formatFileSize(report.size_bytes)}
              </td>
              <td role="cell" data-label="Empreinte SHA-256">
                <code className={styles.hash} title={report.sha256}>
                  {shortHash(report.sha256)}
                </code>
              </td>
              <td role="cell" className={styles.action}>
                <button
                  type="button"
                  className={styles.button}
                  disabled={downloadingId === report.report_id}
                  aria-label={`Télécharger ${report.title}`}
                  onClick={() => onDownload(report)}
                >
                  {downloadingId === report.report_id ? "Téléchargement…" : "Télécharger"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
