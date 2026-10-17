import styles from "./PageHeader.module.css";

interface PageHeaderProps {
  title: string;
  intro: string;
}

/** Titre de page (h1, focalisable par programme au changement de page) et phrase d'introduction. */
export default function PageHeader({ title, intro }: PageHeaderProps) {
  return (
    <div className={styles.header}>
      <h1 className={styles.title} tabIndex={-1}>
        {title}
      </h1>
      <p className={styles.intro}>{intro}</p>
    </div>
  );
}
