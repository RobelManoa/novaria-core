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
      coverage: { provider: "v8", reporter: ["text", "lcov"], reportsDirectory: "coverage" },
    },
  };
});
