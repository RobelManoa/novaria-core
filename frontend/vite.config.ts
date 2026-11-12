/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // API_TARGET : `dev.py front-dev --stub` vise la maquette des prévisions (scripts/dev/forecast_stub.py) au lieu de l'API.
  const { API_TARGET } = loadEnv(mode, ".", "API_");
  return {
    plugins: [react()],
    resolve: { alias: { "@": decodeURIComponent(new URL("./src", import.meta.url).pathname) } },
    server: {
      port: 5173,
      proxy: { "/api": { target: API_TARGET ?? "http://localhost:8000", changeOrigin: true } },
    },
    test: {
      css: true,
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      // Seuls les tests de tests/ : le parcours de bout en bout (e2e/) est lancé par Playwright, pas par Vitest.
      include: ["tests/**/*.test.{ts,tsx}"],
      coverage: {
        provider: "v8",
        reporter: ["text", "lcov"],
        reportsDirectory: "coverage",
        // Le code de l'application. Sans `include`, un fichier que aucun test n'importe n'apparaîtrait pas dans la
        // mesure : il faut le compter pour que le chiffre soit honnête. Types générés et amorçage exclus.
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/types/api/**", "src/**/*.d.ts"],
        // Barrière de FE-08 : sous 70 %, `npm test` échoue (la mesure du jour est bien au-dessus, voir rapport-tests.md).
        thresholds: { statements: 70, branches: 70, functions: 70, lines: 70 },
      },
    },
  };
});
