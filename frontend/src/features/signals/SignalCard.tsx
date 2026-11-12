import { formatDateTime } from "@/features/dashboard/format";
import { SOURCE_LABELS } from "@/features/dashboard/labels";
import type { SignalState } from "@/services/reponse";
import { APPROACH_LABELS, MODE_HINTS, MODE_LABELS, ORIGIN_LABELS, refusalLabel } from "./labels";
import styles from "./Signals.module.css";

interface SignalCardProps {
  signal: SignalState;
  selected: boolean;
  onSelect: () => void;
}

/** L'état d'un carrefour : mode, signal, phase en cours et plan appliqué. */
export default function SignalCard({ signal, selected, onSelect }: Readonly<SignalCardProps>) {
  const allRed = signal.signal === "ALL_RED";
  const simulated = signal.provenance.source_type === "SIMULATED";
  const titleId = `signal-${signal.intersection_id}`;
  return (
    <article
      className={`${styles.card} ${selected ? styles.selected : ""}`}
      aria-labelledby={titleId}
      data-intersection={signal.intersection_id}
    >
      <header className={styles.cardHeader}>
        <h3 id={titleId} className={styles.cardTitle}>
          {signal.intersection_id}
        </h3>
        <span className={`${styles.badge} ${styles[signal.mode]}`} title={MODE_HINTS[signal.mode]}>
          {MODE_LABELS[signal.mode]}
        </span>
      </header>

      <p className={`${styles.signal} ${allRed ? styles.allRed : styles.green}`}>
        <span className={styles.lamp} aria-hidden="true" />
        {allRed
          ? "Tout au rouge (dégagement)"
          : signal.green_approaches.length === 0
            ? "Aucune approche au vert"
            : `Vert : ${signal.green_approaches.map((approach) => APPROACH_LABELS[approach]).join(", ")}`}
      </p>

      <dl className={styles.facts}>
        <div>
          <dt>Phase en cours</dt>
          <dd data-testid="current-phase">{signal.current_phase_id}</dd>
        </div>
        <div>
          <dt>Fin prévue (UTC)</dt>
          <dd>{formatDateTime(Date.parse(signal.phase_ends_at))}</dd>
        </div>
        <div>
          <dt>Décision</dt>
          <dd>
            {ORIGIN_LABELS[signal.decision.origin]}
            {signal.decision.outcome === "REFUSED"
              ? ` (refusée : ${refusalLabel(signal.decision.refusal_reason)})`
              : ""}
          </dd>
        </div>
        <div>
          <dt>Données</dt>
          <dd>
            {simulated ? <span className={styles.simulated}>Simulé</span> : null}{" "}
            <span className={styles.muted}>{SOURCE_LABELS[signal.provenance.source_type]}</span>
          </dd>
        </div>
      </dl>

      <ol className={styles.plan} aria-label={`Plan du carrefour ${signal.intersection_id}`}>
        {signal.phases.map((phase) => (
          <li
            key={phase.phase_id}
            className={phase.phase_id === signal.current_phase_id ? styles.currentPhase : undefined}
            aria-current={phase.phase_id === signal.current_phase_id ? "step" : undefined}
          >
            <strong>{phase.phase_id}</strong>
            <span>{phase.green_approaches.join(" ")}</span>
            <span className={styles.muted}>{phase.duration_s} s</span>
          </li>
        ))}
      </ol>

      <button type="button" className={styles.button} aria-pressed={selected} onClick={onSelect}>
        {selected ? "Carrefour sélectionné" : "Choisir ce carrefour"}
      </button>
    </article>
  );
}
