import type { ReactNode } from "react";
import styles from "./VisuallyHidden.module.css";

/** Texte lu par les lecteurs d'écran mais invisible à l'écran. */
export default function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className={styles.hidden}>{children}</span>;
}
