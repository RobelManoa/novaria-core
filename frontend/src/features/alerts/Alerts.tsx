import { useState } from "react";
import StateMessage from "@/components/StateMessage";
import { useAuth } from "@/features/auth/AuthContext";
import { formatDateTime } from "@/features/dashboard/format";
import { SOURCE_LABELS } from "@/features/dashboard/labels";
import { messageFor } from "@/services/errors";
import type { Alert } from "@/services/alerte";
import styles from "./Alerts.module.css";
import {
  CAUSE_LABELS,
  KIND_LABELS,
  RESOLUTION_LABELS,
  SEVERITY_LABELS,
  STATE_LABELS,
  STREAM_LABELS,
} from "./labels";
import { canAcknowledge, isActive } from "./merge";
import { useAlerts } from "./useAlerts";

type Filter = "active" | "all";

function Row({
  alert,
  canAct,
  busy,
  onAcknowledge,
  onResolve,
}: Readonly<{
  alert: Alert;
  canAct: boolean;
  busy: boolean;
  onAcknowledge: () => void;
  onResolve: () => void;
}>) {
  const simulated = alert.provenance.source_type === "SIMULATED";
  return (
    <tr data-state={alert.state}>
      <td>{formatDateTime(Date.parse(alert.opened_at))}</td>
      <td>{alert.road_segment_id}</td>
      <td>{KIND_LABELS[alert.kind]}</td>
      <td>
        <span className={`${styles.badge} ${styles[alert.severity]}`}>
          {SEVERITY_LABELS[alert.severity]}
        </span>
      </td>
      <td>
        <span className={`${styles.badge} ${styles[alert.state]}`}>
          {STATE_LABELS[alert.state]}
        </span>
        {alert.resolution ? (
          <span className={styles.muted}> ({RESOLUTION_LABELS[alert.resolution]})</span>
        ) : null}
      </td>
      <td>{CAUSE_LABELS[alert.cause]}</td>
      <td>
        {simulated ? <span className={styles.simulated}>Simulé</span> : null}
        <span className={styles.muted}> {SOURCE_LABELS[alert.provenance.source_type]}</span>
      </td>
      <td>
        {canAct && alert.state !== "RESOLVED" ? (
          <span className={styles.actions}>
            {canAcknowledge(alert) ? (
              <button
                type="button"
                className={styles.button}
                disabled={busy}
                onClick={onAcknowledge}
              >
                Acquitter
              </button>
            ) : null}
            <button type="button" className={styles.button} disabled={busy} onClick={onResolve}>
              Résoudre
            </button>
          </span>
        ) : null}
      </td>
    </tr>
  );
}

/**
 * Alertes usager en direct (MS-11, EXG-TDB-03) : la liste de l'API, mise à jour par le flux sans
 * rechargement. Acquitter et résoudre sont réservés à l'opérateur et à l'administrateur.
 */
export default function Alerts() {
  const { user } = useAuth();
  const { alerts, phase, stream, busy, actionError, acknowledge, resolve, retry } = useAlerts();
  const [filter, setFilter] = useState<Filter>("active");
  const canAct = user?.role === "operator" || user?.role === "admin";

  if (phase.status === "loading") {
    return <StateMessage kind="loading" title="Chargement des alertes…" />;
  }
  if (phase.status === "error") {
    return (
      <StateMessage
        kind="error"
        title="Les alertes n'ont pas pu être chargées."
        action={
          <button type="button" className={styles.button} onClick={retry}>
            Réessayer
          </button>
        }
      >
        {messageFor(phase.error)}
      </StateMessage>
    );
  }

  const shown = filter === "active" ? alerts.filter(isActive) : alerts;
  const active = alerts.filter(isActive).length;
  return (
    <div className={styles.content}>
      <div className={styles.bar}>
        <p className={`${styles.stream} ${styles[stream]}`} role="status">
          {STREAM_LABELS[stream]}
        </p>
        <p className={styles.count}>
          {active === 0
            ? "Aucune alerte active"
            : active === 1
              ? "1 alerte active"
              : `${active} alertes actives`}
        </p>
        <label className={styles.field}>
          <span className={styles.label}>Afficher</span>
          <select
            className={styles.select}
            value={filter}
            onChange={(event) => setFilter(event.target.value as Filter)}
          >
            <option value="active">Les alertes actives</option>
            <option value="all">Toutes les alertes</option>
          </select>
        </label>
      </div>
      {actionError ? (
        <p className={styles.error} role="alert">
          {actionError}
        </p>
      ) : null}
      {shown.length === 0 ? (
        <StateMessage kind="empty" title="Aucune alerte à afficher.">
          {filter === "active"
            ? "La circulation est normale sur les tronçons surveillés."
            : "Aucune alerte n'a encore été émise."}
        </StateMessage>
      ) : (
        <div className={styles.wrap}>
          <table className={styles.table}>
            <caption className={styles.caption}>
              Alertes, de la plus récente à la plus ancienne
            </caption>
            <thead>
              <tr>
                <th scope="col">Ouverture (UTC)</th>
                <th scope="col">Tronçon</th>
                <th scope="col">Type</th>
                <th scope="col">Gravité</th>
                <th scope="col">État</th>
                <th scope="col">Cause</th>
                <th scope="col">Données</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((alert) => (
                <Row
                  key={alert.alert_id}
                  alert={alert}
                  canAct={canAct}
                  busy={busy === alert.alert_id}
                  onAcknowledge={() => void acknowledge(alert.alert_id)}
                  onResolve={() => void resolve(alert.alert_id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
