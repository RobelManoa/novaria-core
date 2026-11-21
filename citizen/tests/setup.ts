import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Chaque test repart de l'accueil : un test qui ouvre un détail ne laisse pas son adresse au suivant.
afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", window.location.pathname);
});

// jsdom ne sait pas faire défiler la page : sans ceci, chaque changement d'écran écrit une erreur « non implémenté ».
window.scrollTo = () => {};
