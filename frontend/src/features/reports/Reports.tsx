import { useState } from "react";
import StateMessage from "@/components/StateMessage";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { isApiError, messageFor } from "@/services/errors";
import { downloadReport, type Report } from "@/services/traitement";
import { loadReportPage, mergeReports, type ReportPage } from "./load";
import styles from "./Reports.module.css";
import ReportsTable from "./ReportsTable";
import { saveBlob } from "./save";

const LIST_NOT_FOUND =
  "Le service des rapports n'est pas encore disponible sur ce serveur : la route /api/v1/reports n'est pas servie.";
const DOWNLOAD_NOT_FOUND =
  "Ce rapport est introuvable : il a peut-être été supprimé. Actualisez la liste.";

/**
 * Message d'une erreur. Un 404 n'a pas le même sens partout : sur la liste, la route n'est pas servie (le
 * contrat n'en prévoit pas d'autre) ; sur le téléchargement, le rapport n'existe plus.
 */
function describeError(error: unknown, notFound: string): string {
  if (isApiError(error) && error.status === 404) return notFound;
  const reference =
    isApiError(error) && error.correlationId ? ` Référence à citer : ${error.correlationId}.` : "";
  return `${messageFor(error)}${reference}`;
}

function countLabel(count: number, more: boolean): string {
  const noun = count > 1 ? "rapports affichés" : "rapport affiché";
  return `${count} ${noun}${more ? ", d'autres sont disponibles" : ""}`;
}

function Panel({ first, onRefresh }: Readonly<{ first: ReportPage; onRefresh: () => void }>) {
  const [reports, setReports] = useState<Report[]>(first.items);
  const [cursor, setCursor] = useState(first.nextCursor);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  async function showMore() {
    if (cursor === null) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await loadReportPage(cursor);
      setReports((shown) => mergeReports(shown, page.items));
      setCursor(page.nextCursor);
    } catch (error) {
      setMoreError(`La page suivante n'a pas pu être lue. ${describeError(error, LIST_NOT_FOUND)}`);
    } finally {
      setLoadingMore(false);
    }
  }

  async function download(report: Report) {
    setDownloadingId(report.report_id);
    setDownloadError(null);
    try {
      saveBlob(await downloadReport(report.report_id), report.file_name);
    } catch (error) {
      setDownloadError(
        `Le téléchargement de « ${report.title} » a échoué. ${describeError(error, DOWNLOAD_NOT_FOUND)}`,
      );
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div className={styles.content}>
      <div className={styles.toolbar}>
        <p className={styles.count} role="status">
          {countLabel(reports.length, cursor !== null)}
        </p>
        <button
          type="button"
          className={`${styles.button} ${styles.secondary}`}
          onClick={onRefresh}
        >
          Actualiser
        </button>
      </div>
      {downloadError ? (
        <p className={styles.error} role="alert">
          {downloadError}
        </p>
      ) : null}
      <ReportsTable reports={reports} downloadingId={downloadingId} onDownload={download} />
      {moreError ? (
        <p className={styles.error} role="alert">
          {moreError}
        </p>
      ) : null}
      {cursor !== null ? (
        <div>
          <button
            type="button"
            className={styles.button}
            disabled={loadingMore}
            onClick={() => void showMore()}
          >
            {loadingMore ? "Chargement…" : "Afficher la suite"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Page des rapports : la liste de ceux que le robot a générés, et leur téléchargement. */
export default function Reports() {
  // `generation` relit la première page ; `key` repart d'une liste neuve (pages suivantes oubliées).
  const [generation, setGeneration] = useState(0);
  const { state, reload } = useAsyncResource(`reports|${generation}`, () => loadReportPage());

  if (state.status === "loading") {
    return <StateMessage kind="loading" title="Chargement des rapports…" />;
  }
  if (state.status === "error") {
    return (
      <StateMessage
        kind="error"
        title="Impossible de charger les rapports"
        action={
          <button type="button" className={styles.button} onClick={reload}>
            Réessayer
          </button>
        }
      >
        {describeError(state.error, LIST_NOT_FOUND)}
      </StateMessage>
    );
  }
  if (state.data.items.length === 0) {
    return (
      <StateMessage
        kind="empty"
        title="Aucun rapport généré pour le moment"
        action={
          <button type="button" className={styles.button} onClick={reload}>
            Actualiser
          </button>
        }
      >
        Le robot n&apos;a déposé aucun rapport. Il apparaîtra ici dès qu&apos;il en aura produit un.
      </StateMessage>
    );
  }
  return (
    <Panel key={generation} first={state.data} onRefresh={() => setGeneration((n) => n + 1)} />
  );
}
