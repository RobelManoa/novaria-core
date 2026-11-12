import StateMessage from "@/components/StateMessage";
import { useAuth } from "@/features/auth/AuthContext";
import { formatDateTime } from "@/features/dashboard/format";
import { messageFor } from "@/services/errors";
import { ACTION_LABELS, refusalLabel, STATUS_LABELS } from "./labels";
import styles from "./Signals.module.css";
import { useCommandHistory } from "./useCommandHistory";

/** L'API journalise l'identifiant du compte, pas son nom : le sien se reconnaît, les autres s'abrègent. */
function whoLabel(requestedBy: string, ownId: string | undefined): string {
  if (requestedBy === ownId) return "Vous";
  return requestedBy.length > 12 ? `${requestedBy.slice(0, 8)}…` : requestedBy;
}

/** Journal des commandes d'un carrefour : qui, quand, quoi, pourquoi, et la décision des garde-fous. */
export default function CommandHistory({ intersectionId }: Readonly<{ intersectionId: string }>) {
  const { user } = useAuth();
  const { phase, items, hasMore, loadingMore, loadError, loadMore, reload } =
    useCommandHistory(intersectionId);

  if (phase.status === "loading") {
    return <StateMessage kind="loading" title="Chargement de l'historique…" />;
  }
  if (phase.status === "error") {
    return (
      <StateMessage
        kind="error"
        title="L'historique n'a pas pu être chargé."
        action={
          <button type="button" className={styles.button} onClick={reload}>
            Réessayer
          </button>
        }
      >
        {messageFor(phase.error)}
      </StateMessage>
    );
  }
  if (items.length === 0) {
    return (
      <StateMessage kind="empty" title="Aucune commande pour ce carrefour.">
        Le carrefour n'a reçu aucune commande manuelle.
      </StateMessage>
    );
  }
  return (
    <div className={styles.history}>
      <div className={styles.wrap}>
        <table className={styles.table}>
          <caption className={styles.caption}>
            {`Commandes de ${intersectionId}, de la plus récente à la plus ancienne`}
          </caption>
          <thead>
            <tr>
              <th scope="col">Date (UTC)</th>
              <th scope="col">Opérateur</th>
              <th scope="col">Action</th>
              <th scope="col">Phase</th>
              <th scope="col">Durée</th>
              <th scope="col">Motif</th>
              <th scope="col">Statut</th>
            </tr>
          </thead>
          <tbody>
            {items.map((command) => (
              <tr key={command.command_id} data-status={command.status}>
                <td>{formatDateTime(Date.parse(command.requested_at))}</td>
                <td title={command.requested_by}>
                  {whoLabel(command.requested_by, user?.user_id)}
                </td>
                <td>{ACTION_LABELS[command.action]}</td>
                <td>{command.phase_id ?? "—"}</td>
                <td>{command.duration_s ? `${command.duration_s} s` : "—"}</td>
                <td className={styles.reason}>{command.reason}</td>
                <td>
                  <span className={`${styles.badge} ${styles[command.status]}`}>
                    {STATUS_LABELS[command.status]}
                  </span>
                  {command.refusal_reason ? (
                    <span className={styles.muted}> {refusalLabel(command.refusal_reason)}</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {loadError ? (
        <p className={styles.error} role="alert">
          {messageFor(loadError)}
        </p>
      ) : null}
      {hasMore ? (
        <button
          type="button"
          className={styles.button}
          disabled={loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore ? "Chargement…" : "Afficher les commandes plus anciennes"}
        </button>
      ) : null}
    </div>
  );
}
