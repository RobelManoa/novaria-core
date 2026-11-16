import { defineConfig } from "@playwright/test";

/**
 * Parcours de bout en bout (MS-14) : le navigateur, le front (Vite) et la pile Docker réelle derrière la
 * passerelle (`make up` / `dev.py up`). Rien n'est simulé. Les comptes viennent de l'environnement :
 * E2E_OPERATOR_USER, E2E_VIEWER_USER, E2E_PASSWORD (jamais écrits dans un fichier du dépôt).
 *
 * Lancer :  npm run e2e   (Chrome installé sur le poste ; E2E_CHROME_PATH pour un autre chemin)
 */
const PORT = 5173;

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`,
    channel: process.env.E2E_CHROME_PATH ? undefined : "chrome",
    launchOptions: process.env.E2E_CHROME_PATH
      ? { executablePath: process.env.E2E_CHROME_PATH }
      : {},
    locale: "fr-FR",
    viewport: { width: 1280, height: 900 },
    trace: "off",
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        // API_TARGET : la passerelle de la pile locale (port GATEWAY_PORT, 8000 par défaut).
        command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${PORT} --strictPort`,
        url: `http://127.0.0.1:${PORT}`,
        reuseExistingServer: true,
        env: { API_TARGET: process.env.API_TARGET ?? "http://127.0.0.1:8000" },
      },
});
