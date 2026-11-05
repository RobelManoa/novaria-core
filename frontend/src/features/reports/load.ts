import { listReports, type Report } from "@/services/traitement";

/** Rapports lus par appel. Au-delà, « Afficher la suite » lit la page suivante par son curseur. */
export const PAGE_SIZE = 20;

export interface ReportPage {
  items: Report[];
  /** Curseur de la page suivante ; `null` sur la dernière. */
  nextCursor: string | null;
}

/** Une page de rapports, du plus récent au plus ancien (ordre de l'API, conservé tel quel). */
export async function loadReportPage(cursor?: string): Promise<ReportPage> {
  const page = await listReports({ limit: PAGE_SIZE, cursor });
  return { items: page.items, nextCursor: page.next_cursor };
}

/**
 * Ajoute une page à la liste déjà affichée. Un rapport produit entre deux lectures peut décaler les pages
 * et réapparaître : il n'est gardé qu'une fois, à sa première place.
 */
export function mergeReports(shown: readonly Report[], incoming: readonly Report[]): Report[] {
  const known = new Set(shown.map((report) => report.report_id));
  return [...shown, ...incoming.filter((report) => !known.has(report.report_id))];
}
