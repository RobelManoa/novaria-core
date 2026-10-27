import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

/**
 * Règles de dépendance entre dossiers de src/ (voir frontend/README.md) :
 * components ← features ← pages ← app. Un dossier n'importe jamais un dossier « plus haut ».
 * Les importations sont restreintes sous leurs deux formes : alias « @/… » et chemins relatifs.
 */
function forbidImports(folders) {
  return {
    "no-restricted-imports": [
      "error",
      {
        patterns: folders.map((folder) => ({
          group: [`@/${folder}`, `@/${folder}/**`, `**/${folder}`, `**/${folder}/**`],
          message: `Dépendance interdite vers ${folder}/ : voir les règles de dépendance du README.`,
        })),
      },
    ],
  };
}

export default tseslint.config(
  { ignores: ["dist", "coverage", "src/types/api"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: { ...reactHooks.configs.recommended.rules },
  },
  // Tout appel réseau passe par src/services/ : un fetch ailleurs contourne le typage et la gestion d'erreurs.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/services/**"],
    rules: {
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: "Appeler l'API par une fonction de src/services/." },
      ],
      "no-restricted-properties": [
        "error",
        {
          object: "globalThis",
          property: "fetch",
          message: "Appeler l'API par une fonction de src/services/.",
        },
      ],
    },
  },
  // components/ est générique : il n'importe ni features/, ni pages/, ni app/.
  { files: ["src/components/**/*.{ts,tsx}"], rules: forbidImports(["features", "pages", "app"]) },
  // features/ n'importe ni pages/ ni app/.
  { files: ["src/features/**/*.{ts,tsx}"], rules: forbidImports(["pages", "app"]) },
  // hooks/, services/ et types/ restent indépendants de l'interface.
  {
    files: ["src/hooks/**/*.{ts,tsx}", "src/services/**/*.{ts,tsx}", "src/types/**/*.{ts,tsx}"],
    rules: forbidImports(["components", "features", "pages", "app"]),
  },
);
