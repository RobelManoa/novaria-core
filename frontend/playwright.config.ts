import { defineConfig } from "@playwright/test";

/**
 * Parcours de bout en bout (FE-08) : un vrai navigateur ouvre l'application CONSTRUITE (`npm run build`), servie
 * par `vite preview`. Seule l'API est simulée (voir e2e/support.ts) ; tout le reste est réel : routeur, session,
 * client d'API, mise en page, CSS.
 *
 * Navigateur : dans la CI, Chromium installé par `npx playwright install --with-deps chromium`. Sur un poste qui a
 * déjà un navigateur, `E2E_CHANNEL=msedge` (ou `chrome`) évite le téléchargement.
 */
const PORT = 4173;
const channel = process.env.E2E_CHANNEL || undefined;

export default defineConfig({
  testDir: "e2e",
  // Pas de nouvelle tentative : un test instable doit échouer, pas passer au deuxième essai.
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: "e2e-report", open: "never" }],
    ["json", { outputFile: "e2e-report/resultats.json" }],
  ],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel,
    locale: "fr-FR",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
