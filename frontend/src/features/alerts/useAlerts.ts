import { useCallback, useEffect, useState } from "react";
import { acknowledgeAlert, listAlerts, resolveAlert, type Alert } from "@/services/alerte";
import { openAlertStream, type StreamStatus } from "@/services/alertStream";
import { messageFor } from "@/services/errors";
import { mergeAlert, mergeAlerts } from "./merge";

/** Alertes lues à chaque rafraîchissement : les plus récentes, l'écran n'en garde pas davantage. */
const PAGE_SIZE = 200;
/**
 * La liste est relue à ce rythme en plus du flux : le flux ne rejoue rien et ne numérote pas ses messages,
 * un événement manqué (coupure brève, lecteur du serveur redémarré) ne se verrait pas. Au pire, l'écran
 * est faux pendant cet intervalle.
 */
export const REFRESH_MS = 30_000;

export type Phase =
  { status: "loading" } | { status: "ready" } | { status: "error"; error: unknown };

/**
 * Les alertes affichées : la liste de l'API, tenue à jour par le flux en direct.
 *
 * Le flux s'ouvre **avant** la lecture de la liste : un changement survenu entre les deux arrive par
 * le flux et la liste le retrouve, rien n'est manqué. À chaque reconnexion la liste est relue, car les
 * événements d'une coupure ne sont pas rejoués.
 */
export function useAlerts() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [phase, setPhase] = useState<Phase>({ status: "loading" });
  const [stream, setStream] = useState<StreamStatus>("connecting");
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const page = await listAlerts({ limit: PAGE_SIZE });
      setAlerts((current) => mergeAlerts(current, page.items));
      setPhase({ status: "ready" });
    } catch (error) {
      // Un échec de rafraîchissement ne cache pas ce qu'on affiche déjà.
      setPhase((current) => (current.status === "ready" ? current : { status: "error", error }));
    }
  }, []);

  useEffect(() => {
    const close = openAlertStream({
      onAlert: (alert) => setAlerts((current) => mergeAlert(current, alert)),
      onStatus: setStream,
      onLive: () => void refresh(),
    });
    void refresh(); // le flux peut ne jamais s'ouvrir : la liste ne doit pas en dépendre
    const timer = setInterval(() => void refresh(), REFRESH_MS);
    return () => {
      clearInterval(timer);
      close();
    };
  }, [refresh]);

  const act = useCallback(async (alertId: string, action: () => Promise<Alert>) => {
    setBusy(alertId);
    setActionError(null);
    try {
      const updated = await action();
      setAlerts((current) => mergeAlert(current, updated));
    } catch (error) {
      setActionError(messageFor(error));
    } finally {
      setBusy(null);
    }
  }, []);

  const acknowledge = useCallback(
    (alertId: string) => act(alertId, () => acknowledgeAlert(alertId)),
    [act],
  );
  const resolve = useCallback(
    (alertId: string) => act(alertId, () => resolveAlert(alertId, {})),
    [act],
  );

  const retry = useCallback(() => {
    setPhase({ status: "loading" });
    void refresh();
  }, [refresh]);

  return { alerts, phase, stream, busy, actionError, acknowledge, resolve, retry };
}
