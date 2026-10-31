import type { ReactNode } from "react";
import styles from "./StateMessage.module.css";

interface StateMessageProps {
  /** `loading` et `empty` s'annoncent poliment (`status`), `error` aussitôt (`alert`). */
  kind: "loading" | "empty" | "error";
  title: string;
  children?: ReactNode;
  /** Bouton ou lien proposé à l'utilisateur (« Réessayer »). */
  action?: ReactNode;
}

/** Encart d'un état de contenu : chargement en cours, aucune donnée, ou échec. */
export default function StateMessage({
  kind,
  title,
  children,
  action,
}: Readonly<StateMessageProps>) {
  return (
    <div
      className={`${styles.box} ${styles[kind]}`}
      role={kind === "error" ? "alert" : "status"}
      aria-busy={kind === "loading" ? true : undefined}
    >
      <p className={styles.title}>{title}</p>
      {children ? <p className={styles.text}>{children}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
