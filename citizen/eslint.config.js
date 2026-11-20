import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

const DONNEES_SUR_L_APPAREIL = ["localStorage", "sessionStorage", "indexedDB"].map((name) => ({
  name,
  message: "L'application ne garde rien sur l'appareil (ADR-030).",
}));

export default tseslint.config(
  { ignores: ["dist", "coverage", "test-results"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: { ...reactHooks.configs.recommended.rules },
  },
  // Aucune donnée n'est gardée sur l'appareil de l'usager (ADR-030) : ni stockage, ni cookie.
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: { "no-restricted-globals": ["error", ...DONNEES_SUR_L_APPAREIL] },
  },
  // Tout appel réseau passe par src/api.ts : un fetch ailleurs contournerait les garde-fous (pas de jeton, pas de cookie).
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/api.ts"],
    rules: {
      "no-restricted-globals": [
        "error",
        ...DONNEES_SUR_L_APPAREIL,
        { name: "fetch", message: "Appeler l'API par src/api.ts." },
      ],
      "no-restricted-properties": [
        "error",
        { object: "globalThis", property: "fetch", message: "Appeler l'API par src/api.ts." },
        { object: "window", property: "fetch", message: "Appeler l'API par src/api.ts." },
      ],
    },
  },
);
