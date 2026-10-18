import { useEffect } from "react";

/** Appelle `onEscape` à chaque appui sur Échap tant que `active` est vrai. */
export function useEscapeKey(onEscape: () => void, active = true): void {
  useEffect(() => {
    if (!active) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onEscape();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onEscape, active]);
}
