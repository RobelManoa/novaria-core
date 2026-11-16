import { useState } from "react";
import StateMessage from "@/components/StateMessage";
import { formatTime } from "@/features/dashboard/format";
import { messageFor } from "@/services/errors";
import CommandHistory from "./CommandHistory";
import CommandPanel from "./CommandPanel";
import SignalCard from "./SignalCard";
import styles from "./Signals.module.css";
import { useSignals } from "./useSignals";

/**
 * Feux de circulation (MS-14, EXG-TDB-03) : l'état de chaque carrefour, relu à intervalle fixe, la commande
 * manuelle du carrefour choisi (opérateur et administrateur) et le journal de ses commandes.
 */
export default function Signals() {
  const { signals, phase, stale, updatedAt, refresh, retry } = useSignals();
  const [chosen, setChosen] = useState<string | null>(null);
  const [historyKey, setHistoryKey] = useState(0);

  if (phase.status === "loading") {
    return <StateMessage kind="loading" title="Chargement de l'état des feux…" />;
  }
  if (phase.status === "error") {
    return (
      <StateMessage
        kind="error"
        title="L'état des feux n'a pas pu être chargé."
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
  if (signals.length === 0) {
    return (
      <StateMessage kind="empty" title="Aucun carrefour à feux.">
        Le service de réponse ne pilote aucun carrefour pour le moment.
      </StateMessage>
    );
  }

  const selected = signals.find((signal) => signal.intersection_id === chosen) ?? signals[0];
  return (
    <div className={styles.content}>
      <p className={`${styles.stream} ${stale ? styles.offline : styles.live}`} role="status">
        {stale
          ? "Connexion perdue : dernières valeurs connues"
          : `En direct${updatedAt ? ` · mis à jour à ${formatTime(updatedAt)} (UTC)` : ""}`}
      </p>

      <section aria-labelledby="signals-states" className={styles.section}>
        <h2 id="signals-states" className={styles.heading}>
          État des carrefours
        </h2>
        <div className={styles.cards}>
          {signals.map((signal) => (
            <SignalCard
              key={signal.intersection_id}
              signal={signal}
              selected={signal.intersection_id === selected.intersection_id}
              onSelect={() => setChosen(signal.intersection_id)}
            />
          ))}
        </div>
      </section>

      <section aria-labelledby="signals-command" className={styles.section}>
        <h2 id="signals-command" className={styles.heading}>
          Commande manuelle
        </h2>
        <CommandPanel
          key={selected.intersection_id}
          signal={selected}
          onSent={() => {
            setHistoryKey((count) => count + 1);
            void refresh();
          }}
        />
      </section>

      <section aria-labelledby="signals-history" className={styles.section}>
        <h2 id="signals-history" className={styles.heading}>
          Historique des commandes
        </h2>
        <CommandHistory
          key={`${selected.intersection_id}|${historyKey}`}
          intersectionId={selected.intersection_id}
        />
      </section>
    </div>
  );
}
