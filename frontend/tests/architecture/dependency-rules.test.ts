// @vitest-environment node
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const eslint = new ESLint();

async function restrictedImports(filePath: string, code: string): Promise<number> {
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages.filter((message) => message.ruleId === "no-restricted-imports").length;
}

const cases: Array<{ from: string; code: string; forbidden: boolean }> = [
  {
    from: "src/components/X.tsx",
    code: 'import a from "@/features/theme/theme";',
    forbidden: true,
  },
  { from: "src/components/X.tsx", code: 'import a from "@/pages/AlertsPage";', forbidden: true },
  { from: "src/components/X.tsx", code: 'import a from "@/app/App";', forbidden: true },
  {
    from: "src/components/X.tsx",
    code: 'import a from "../features/theme/theme";',
    forbidden: true,
  },
  {
    from: "src/components/X.tsx",
    code: 'import a from "@/hooks/useMediaQuery";',
    forbidden: false,
  },
  { from: "src/components/X.tsx", code: 'import a from "./Container";', forbidden: false },
  { from: "src/features/x/X.tsx", code: 'import a from "@/pages/AlertsPage";', forbidden: true },
  { from: "src/features/x/X.tsx", code: 'import a from "../../app/App";', forbidden: true },
  {
    from: "src/features/x/X.tsx",
    code: 'import a from "@/components/Container";',
    forbidden: false,
  },
  {
    from: "src/features/x/X.tsx",
    code: 'import a from "@/features/theme/theme";',
    forbidden: false,
  },
  { from: "src/pages/X.tsx", code: 'import a from "@/features/theme/theme";', forbidden: false },
  { from: "src/pages/X.tsx", code: 'import a from "@/components/Container";', forbidden: false },
  { from: "src/app/X.tsx", code: 'import a from "@/pages/AlertsPage";', forbidden: false },
  { from: "src/hooks/x.ts", code: 'import a from "@/components/Container";', forbidden: true },
  { from: "src/services/x.ts", code: 'import a from "@/features/theme/theme";', forbidden: true },
  { from: "src/types/x.ts", code: 'import a from "@/pages/AlertsPage";', forbidden: true },
];

describe("règles de dépendance entre dossiers", () => {
  it.each(cases)(
    "$from : $code → interdit = $forbidden",
    async ({ from, code, forbidden }) => {
      const count = await restrictedImports(from, `${code}\nexport default a;\n`);
      expect(count).toBe(forbidden ? 1 : 0);
    },
    30_000,
  );
});

async function networkRuleViolations(filePath: string, code: string): Promise<number> {
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages.filter(
    (message) =>
      message.ruleId === "no-restricted-globals" || message.ruleId === "no-restricted-properties",
  ).length;
}

const fetchCases: Array<{ from: string; code: string; forbidden: boolean }> = [
  { from: "src/pages/X.tsx", code: 'fetch("/api/v1/alerts");', forbidden: true },
  { from: "src/features/x/X.tsx", code: 'fetch("/api/v1/alerts");', forbidden: true },
  { from: "src/hooks/x.ts", code: 'globalThis.fetch("/api/v1/alerts");', forbidden: true },
  { from: "src/components/X.tsx", code: 'fetch("/api/v1/alerts");', forbidden: true },
  { from: "src/services/x.ts", code: 'fetch("/api/v1/alerts");', forbidden: false },
  { from: "src/services/x.ts", code: 'globalThis.fetch("/api/v1/alerts");', forbidden: false },
  {
    from: "src/pages/X.tsx",
    code: 'import { listAlerts } from "@/services/alerte";',
    forbidden: false,
  },
];

describe("tout appel réseau passe par src/services/", () => {
  it.each(fetchCases)(
    "$from : $code → interdit = $forbidden",
    async ({ from, code, forbidden }) => {
      expect(await networkRuleViolations(from, `${code}\n`)).toBe(forbidden ? 1 : 0);
    },
    30_000,
  );
});
