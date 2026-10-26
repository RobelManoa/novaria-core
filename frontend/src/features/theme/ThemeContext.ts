import { createContext, useContext } from "react";
import type { ThemeChoice } from "./theme";

export interface ThemeContextValue {
  theme: ThemeChoice;
  setTheme: (theme: ThemeChoice) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme doit être utilisé dans un ThemeProvider");
  return value;
}
