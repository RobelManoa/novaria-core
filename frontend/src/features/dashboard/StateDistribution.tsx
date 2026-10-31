import type { CongestionState } from "@/services/traitement";
import { STATE_LABELS } from "./labels";
import { STATES } from "./summary";
import styles from "./StateDistribution.module.css";

interface StateDistributionProps {
  counts: Record<CongestionState, number>;
  total: number;
}

/** Répartition des tronçons par état : une barre proportionnelle, et la liste des nombres exacts. */
export default function StateDistribution({ counts, total }: Readonly<StateDistributionProps>) {
  return (
    <div className={styles.box}>
      <div className={styles.bar} aria-hidden="true">
        {STATES.filter((state) => counts[state] > 0).map((state) => (
          <span
            key={state}
            className={`${styles.segment} ${styles[state]}`}
            style={{ width: `${(counts[state] / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className={styles.legend}>
        {STATES.map((state) => (
          <li key={state} className={styles.item}>
            <span className={`${styles.swatch} ${styles[state]}`} aria-hidden="true" />
            <span>{STATE_LABELS[state]}</span> <strong>{counts[state]}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}
