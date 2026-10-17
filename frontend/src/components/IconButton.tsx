import type { ComponentPropsWithRef } from "react";
import styles from "./IconButton.module.css";

interface IconButtonProps extends Omit<ComponentPropsWithRef<"button">, "aria-label"> {
  /** Nom accessible du bouton (obligatoire : l'icône seule ne se lit pas). */
  label: string;
}

/** Bouton réduit à une icône, avec une zone tactile d'au moins 44 px. */
export default function IconButton({ label, className, children, ...props }: IconButtonProps) {
  return (
    <button
      type="button"
      {...props}
      aria-label={label}
      className={className ? `${styles.button} ${className}` : styles.button}
    >
      {children}
    </button>
  );
}
