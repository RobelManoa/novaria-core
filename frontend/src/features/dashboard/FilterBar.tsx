import { PERIODS, WINDOW_SIZES, type Filters, type WindowSizeSeconds } from "./filters";
import styles from "./FilterBar.module.css";

interface FilterBarProps {
  filters: Filters;
  /** Carrefours connus, pour le choix de la zone. */
  zones: readonly string[];
  onChange: (filters: Filters) => void;
}

/** Période, taille de fenêtre et zone : chaque changement relance la lecture de l'API. */
export default function FilterBar({ filters, zones, onChange }: Readonly<FilterBarProps>) {
  // Une zone choisie reste proposée même si la liste connue ne la contient pas.
  const options =
    filters.intersectionId && !zones.includes(filters.intersectionId)
      ? [...zones, filters.intersectionId].sort((a, b) => a.localeCompare(b))
      : zones;

  return (
    <form
      className={styles.bar}
      aria-label="Filtres du tableau de bord"
      onSubmit={(event) => event.preventDefault()}
    >
      <label className={styles.field}>
        <span className={styles.label}>Période</span>
        <select
          className={styles.select}
          value={filters.periodHours}
          onChange={(event) => onChange({ ...filters, periodHours: Number(event.target.value) })}
        >
          {PERIODS.map((period) => (
            <option key={period.hours} value={period.hours}>
              {period.label}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.field}>
        <span className={styles.label}>Taille des fenêtres</span>
        <select
          className={styles.select}
          value={filters.windowSizeS}
          onChange={(event) =>
            onChange({ ...filters, windowSizeS: Number(event.target.value) as WindowSizeSeconds })
          }
        >
          {WINDOW_SIZES.map((size) => (
            <option key={size.seconds} value={size.seconds}>
              {size.label}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.field}>
        <span className={styles.label}>Zone</span>
        <select
          className={styles.select}
          value={filters.intersectionId ?? ""}
          onChange={(event) => onChange({ ...filters, intersectionId: event.target.value || null })}
        >
          <option value="">Tout le réseau</option>
          {options.map((zone) => (
            <option key={zone} value={zone}>
              {`Carrefour ${zone}`}
            </option>
          ))}
        </select>
      </label>
    </form>
  );
}
