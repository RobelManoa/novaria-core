export type ThemeChoice = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "novaria-theme";

export const THEME_OPTIONS: ReadonlyArray<{ value: ThemeChoice; label: string }> = [
  { value: "light", label: "Clair" },
  { value: "dark", label: "Sombre" },
  { value: "system", label: "Système" },
];

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return THEME_OPTIONS.some((option) => option.value === value);
}

/** Lit le choix mémorisé. Le stockage peut être indisponible : on retombe alors sur « Système ». */
export function readStoredTheme(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function storeTheme(theme: ThemeChoice): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Stockage indisponible (navigation privée, données bloquées) : le choix vaut pour la session.
  }
}

/** « Clair » et « Sombre » fixent data-theme sur <html> ; « Système » le retire (préférence du système). */
export function applyTheme(theme: ThemeChoice): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

/** À appeler avant le premier rendu pour éviter un flash de mauvais thème. */
export function initTheme(): ThemeChoice {
  const theme = readStoredTheme();
  applyTheme(theme);
  return theme;
}
