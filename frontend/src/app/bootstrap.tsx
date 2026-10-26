import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { initTheme } from "@/features/theme/theme";
import App from "./App";

/** Applique le thème mémorisé avant le premier rendu (évite un flash), puis monte l'application. */
export function mountApp(container: HTMLElement): Root {
  initTheme();
  const root = createRoot(container);
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  return root;
}
