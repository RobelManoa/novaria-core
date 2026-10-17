import { useState } from "react";
import { type DataRouter, RouterProvider } from "react-router";
import ThemeProvider from "@/features/theme/ThemeProvider";
import { createAppRouter } from "./router";

interface AppProps {
  /** Routeur à utiliser ; par défaut, le routeur navigateur de l'application (les tests fournissent un routeur mémoire). */
  router?: DataRouter;
}

export default function App({ router }: AppProps) {
  const [activeRouter] = useState(() => router ?? createAppRouter());
  return (
    <ThemeProvider>
      <RouterProvider router={activeRouter} />
    </ThemeProvider>
  );
}
