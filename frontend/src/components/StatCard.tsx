import styles from "./StatCard.module.css";

interface StatCardProps {
  label: string;
  /** Valeur déjà formatée ; « — » quand elle n'existe pas. */
  value: string;
  unit?: string;
  /** Phrase qui dit comment la valeur est calculée. */
  hint?: string;
}

/** Carte d'un chiffre clé : un libellé, une valeur, son unité et sa définition. */
export default function StatCard({ label, value, unit, hint }: Readonly<StatCardProps>) {
  return (
    <div className={styles.card}>
      <p className={styles.label}>{label}</p>
      <p className={styles.value}>
        <span>{value}</span>
        {unit ? <span className={styles.unit}> {unit}</span> : null}
      </p>
      {hint ? <p className={styles.hint}>{hint}</p> : null}
    </div>
  );
}
