import { ROLE_LABELS, useAuth } from "./AuthContext";
import styles from "./UserMenu.module.css";

/** Compte connecté (nom et rôle) et bouton de déconnexion, dans l'en-tête. */
export default function UserMenu() {
  const { user, logout } = useAuth();
  return (
    <div className={styles.menu}>
      {user && (
        <span className={styles.identity}>
          {user.username} · {ROLE_LABELS[user.role]}
        </span>
      )}
      <button type="button" className={styles.logout} onClick={logout}>
        Se déconnecter
      </button>
    </div>
  );
}
