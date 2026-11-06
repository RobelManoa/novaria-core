import type { Alert, AlertState } from "@/services/alerte";

/** Nombre maximal d'alertes gardées à l'écran : les plus anciennes sortent en premier. */
export const MAX_ALERTS = 200;

/** Avancement dans le cycle de vie : une alerte ne recule jamais (ADR-028). */
const PROGRESS: Record<AlertState, number> = {
  CREATED: 0,
  NOTIFIED: 1,
  ACKNOWLEDGED: 2,
  RESOLVED: 3,
};

function newestFirst(alerts: Alert[]): Alert[] {
  return [...alerts]
    .sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at))
    .slice(0, MAX_ALERTS);
}

/**
 * Range une alerte reçue (flux, liste ou réponse à une action) parmi celles qu'on affiche.
 *
 * Une alerte déjà connue est complétée, jamais ramenée à un état antérieur : une liste lue un peu plus
 * tôt peut arriver après l'événement qui l'a dépassée. L'événement du flux ne porte pas tous les champs
 * de l'API (`notified_at`, `acknowledged_by`) : ceux qu'on avait sont gardés.
 */
export function mergeAlert(alerts: Alert[], incoming: Alert): Alert[] {
  const index = alerts.findIndex((alert) => alert.alert_id === incoming.alert_id);
  if (index === -1) return newestFirst([incoming, ...alerts]);
  const current = alerts[index];
  if (PROGRESS[incoming.state] < PROGRESS[current.state]) return alerts;
  return newestFirst(
    alerts.map((alert, position) => (position === index ? { ...current, ...incoming } : alert)),
  );
}

export function mergeAlerts(alerts: Alert[], incoming: Alert[]): Alert[] {
  return incoming.reduce(mergeAlert, alerts);
}

/** Alerte à traiter : ni résolue, ni sans suite. */
export function isActive(alert: Alert): boolean {
  return alert.state !== "RESOLVED";
}

/** L'opérateur peut acquitter une alerte qui ne l'est pas encore et n'est pas résolue. */
export function canAcknowledge(alert: Alert): boolean {
  return alert.state === "CREATED" || alert.state === "NOTIFIED";
}
