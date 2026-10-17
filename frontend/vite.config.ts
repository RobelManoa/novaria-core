/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": decodeURIComponent(new URL("./src", import.meta.url).pathname) } },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
  test: {
    css: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    coverage: { provider: "v8", reporter: ["text", "lcov"], reportsDirectory: "coverage" },
  },
});
