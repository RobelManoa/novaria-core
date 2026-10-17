import type { ReactNode } from "react";
import styles from "./Container.module.css";

/** Colonne de contenu centrée, de largeur maximale limitée. */
export default function Container({ children }: { children: ReactNode }) {
  return <div className={styles.container}>{children}</div>;
}
