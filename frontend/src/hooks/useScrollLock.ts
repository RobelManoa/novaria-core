import { useEffect } from "react";

const LOCK_CLASS = "scroll-locked";

/** Bloque le défilement de la page (classe définie dans styles/global.css) tant que `locked` est vrai. */
export function useScrollLock(locked: boolean): void {
  useEffect(() => {
    if (!locked) return;
    document.body.classList.add(LOCK_CLASS);
    return () => document.body.classList.remove(LOCK_CLASS);
  }, [locked]);
}
