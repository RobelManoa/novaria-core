import { type FormEvent, useId, useState } from "react";
import { messageFor } from "@/services/errors";
import { useAuth } from "./AuthContext";
import styles from "./LoginForm.module.css";

interface LoginFormProps {
  /** Appelé une fois la session ouverte. */
  onSuccess: () => void;
}

/** Formulaire de connexion : identifiant, mot de passe, message d'erreur annoncé aux lecteurs d'écran. */
export default function LoginForm({ onSuccess }: Readonly<LoginFormProps>) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const usernameId = useId();
  const passwordId = useId();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await login(username.trim(), password);
      onSuccess();
    } catch (error) {
      setMessage(messageFor(error));
      setPassword("");
      setSubmitting(false);
    }
  }

  return (
    <form
      className={styles.form}
      onSubmit={handleSubmit}
      aria-describedby={message ? "login-erreur" : undefined}
    >
      {message && (
        <p id="login-erreur" role="alert" className={styles.error}>
          {message}
        </p>
      )}
      <div className={styles.field}>
        <label htmlFor={usernameId}>Identifiant</label>
        <input
          id={usernameId}
          name="username"
          type="text"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
      </div>
      <div className={styles.field}>
        <label htmlFor={passwordId}>Mot de passe</label>
        <input
          id={passwordId}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      <button type="submit" className={styles.submit} disabled={submitting}>
        {submitting ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
}
