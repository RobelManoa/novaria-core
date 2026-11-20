/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // API_TARGET : la passerelle (par défaut http://localhost:8000). L'application appelle `/api/...` sur sa propre origine,
  // Vite relaie : aucune configuration CORS n'est nécessaire en développement (CIT-06 fixera l'origine autorisée).
  const { API_TARGET } = loadEnv(mode, ".", "API_");
  const cible = { target: API_TARGET ?? "http://localhost:8000", changeOrigin: true };
  return {
    plugins: [react()],
    server: { port: 5174, host: "127.0.0.1", proxy: { "/api": cible } },
    preview: { port: 5174, host: "127.0.0.1", proxy: { "/api": cible } },
    test: {
      css: false,
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      include: ["tests/**/*.test.{ts,tsx}"],
      coverage: {
        provider: "v8",
        reporter: ["text", "lcov"],
        reportsDirectory: "coverage",
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/**/*.d.ts", "src/main.tsx"],
        thresholds: { statements: 85, branches: 80, functions: 85, lines: 85 },
      },
    },
  };
});
