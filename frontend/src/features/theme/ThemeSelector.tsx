import { THEME_OPTIONS } from "./theme";
import { useTheme } from "./ThemeContext";
import styles from "./ThemeSelector.module.css";

/** Choix du thème : trois boutons radio natifs (clavier, toucher, état annoncé par le navigateur). */
export default function ThemeSelector() {
  const { theme, setTheme } = useTheme();
  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>Thème de l'interface</legend>
      {THEME_OPTIONS.map((option) => (
        <label key={option.value} className={styles.option}>
          <input
            className={styles.input}
            type="radio"
            name="theme"
            value={option.value}
            checked={theme === option.value}
            onChange={() => setTheme(option.value)}
          />
          <span className={styles.label}>{option.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
