import { useEffect, useState } from "react";
import { getHealth, type Health } from "@/services/api";
import { isApiError, messageFor } from "@/services/errors";
import styles from "./ApiStatus.module.css";

/** Texte de l'indicateur quand l'appel échoue : le code HTTP aide à diagnostiquer, la phrase explique. */
function describeFailure(error: unknown): string {
  if (isApiError(error) && error.status > 0) return `API indisponible (${error.status})`;
  return `API injoignable : ${messageFor(error)}`;
}

/** Indicateur de l'état de l'API : en ligne (status), indisponible (alert) ou vérification en cours. */
export default function ApiStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(describeFailure(e)));
  }, []);

  if (error) {
    return (
      <p role="alert" className={`${styles.badge} ${styles.error}`}>
        {error}
      </p>
    );
  }
  if (health) {
    return (
      <p role="status" className={`${styles.badge} ${styles.ok}`}>
        <span className={styles.dot} aria-hidden="true" />
        <span>API en ligne</span>
        <span className={styles.details}>
          · version {health.version} · révision {health.revision}
        </span>
      </p>
    );
  }
  return <p className={styles.badge}>Vérification de l'API…</p>;
}
