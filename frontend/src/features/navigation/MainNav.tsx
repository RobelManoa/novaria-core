import { NavLink } from "react-router";
import { EXTERNAL_ENTRIES, NAV_ENTRIES } from "./entries";
import styles from "./MainNav.module.css";

interface MainNavProps {
  /** Appelé au clic sur un lien (le tiroir mobile se referme). */
  onNavigate?: () => void;
}

/** Liste des liens du menu ; NavLink pose aria-current="page" sur le lien actif. */
export default function MainNav({ onNavigate }: MainNavProps) {
  return (
    <ul className={styles.list}>
      {NAV_ENTRIES.map((entry) => (
        <li key={entry.path}>
          <NavLink
            to={entry.path}
            end={entry.path === "/"}
            className={({ isActive }) =>
              isActive ? `${styles.link} ${styles.active}` : styles.link
            }
            onClick={onNavigate}
          >
            {entry.label}
          </NavLink>
        </li>
      ))}
      {EXTERNAL_ENTRIES.map((entry) => (
        <li key={entry.href}>
          <a
            href={entry.href}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.link}
            title={entry.hint}
          >
            {entry.label}
            <span aria-hidden="true"> ↗</span>
            <span className={styles.srOnly}> ({entry.hint})</span>
          </a>
        </li>
      ))}
    </ul>
  );
}
