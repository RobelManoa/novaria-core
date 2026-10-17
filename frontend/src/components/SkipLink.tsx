import styles from "./SkipLink.module.css";

/** Premier élément focalisable de la page : permet de passer directement au contenu. */
export default function SkipLink({ targetId, children }: { targetId: string; children: string }) {
  return (
    <a className={styles.skip} href={`#${targetId}`}>
      {children}
    </a>
  );
}
