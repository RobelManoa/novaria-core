import { describe, expect, it } from "vitest";
import { BREAKPOINTS, DESKTOP_QUERY, TABLET_QUERY } from "@/styles/breakpoints";
import tokensCss from "@/styles/tokens.css?raw";

type Tokens = Record<string, string>;

function parseBlocks(css: string): { light: Tokens; dark: Tokens; darkSystem: Tokens } {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const blocks: Record<string, Tokens> = {};
  const pattern =
    /(:root\[data-theme="dark"\]|:root:not\(\[data-theme="light"\]\)|:root)\s*\{([^}]*)\}/g;
  for (const match of source.matchAll(pattern)) {
    const tokens: Tokens = {};
    for (const declaration of match[2].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      tokens[declaration[1]] = declaration[2].trim();
    }
    blocks[match[1]] = tokens;
  }
  return {
    light: blocks[":root"],
    dark: blocks[':root[data-theme="dark"]'],
    darkSystem: blocks[':root:not([data-theme="light"])'],
  };
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((start) => {
    const value = parseInt(hex.slice(start, start + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

const { light, dark, darkSystem } = parseBlocks(tokensCss);
const themes: Record<string, Tokens> = { clair: light, sombre: { ...light, ...dark } };

const REQUIRED_COLORS = [
  "bg",
  "surface",
  "surface-raised",
  "text",
  "text-muted",
  "border",
  "border-strong",
  "primary",
  "primary-contrast",
  "focus",
  "success",
  "success-bg",
  "warning",
  "warning-bg",
  "danger",
  "danger-bg",
  "info",
  "info-bg",
].map((name) => `--color-${name}`);

describe("jetons de design", () => {
  it("définit les échelles d'espacement et de typographie", () => {
    for (let step = 1; step <= 8; step++) expect(light).toHaveProperty(`--space-${step}`);
    for (const size of ["xs", "sm", "md", "lg", "xl", "2xl", "3xl"]) {
      expect(light).toHaveProperty(`--text-${size}`);
    }
    expect(light["--tap-min"]).toBe("2.75rem");
    expect(light["--font-sans"]).not.toMatch(/https?:/);
  });

  it.each(Object.keys(themes))("définit toutes les couleurs sémantiques (thème %s)", (name) => {
    for (const token of REQUIRED_COLORS) expect(themes[name]).toHaveProperty(token);
  });

  it("garde le jeu sombre identique pour le choix explicite et pour le mode système", () => {
    expect(darkSystem).toEqual(dark);
  });

  describe.each(Object.keys(themes))("contrastes WCAG AA (thème %s)", (name) => {
    const t = themes[name];
    const ratio = (fg: string, bg: string) => contrast(t[`--color-${fg}`], t[`--color-${bg}`]);

    it.each(["bg", "surface", "surface-raised"])("texte sur %s : 4,5:1 minimum", (bg) => {
      expect(ratio("text", bg)).toBeGreaterThanOrEqual(4.5);
      expect(ratio("text-muted", bg)).toBeGreaterThanOrEqual(4.5);
      expect(ratio("primary", bg)).toBeGreaterThanOrEqual(4.5);
    });

    it("texte du bouton principal : 4,5:1 minimum", () => {
      expect(ratio("primary-contrast", "primary")).toBeGreaterThanOrEqual(4.5);
    });

    it.each(["success", "warning", "danger", "info"])("état %s : texte sur son fond", (state) => {
      expect(ratio(state, `${state}-bg`)).toBeGreaterThanOrEqual(4.5);
      expect(ratio(state, "surface")).toBeGreaterThanOrEqual(4.5);
    });

    it.each(["bg", "surface", "surface-raised"])(
      "anneau de focus et bordures d'interface sur %s : 3:1",
      (bg) => {
        expect(ratio("focus", bg)).toBeGreaterThanOrEqual(3);
        expect(ratio("border-strong", bg)).toBeGreaterThanOrEqual(3);
      },
    );
  });
});

describe("points de rupture", () => {
  it("restent identiques dans tokens.css et breakpoints.ts", () => {
    expect(tokensCss).toContain(`breakpoint-tablet: ${BREAKPOINTS.tablet}`);
    expect(tokensCss).toContain(`breakpoint-desktop: ${BREAKPOINTS.desktop}`);
    expect(TABLET_QUERY).toBe("(min-width: 40rem)");
    expect(DESKTOP_QUERY).toBe("(min-width: 64rem)");
  });
});

describe("feuilles de style des composants", () => {
  const sheets = import.meta.glob("/src/**/*.module.css", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  it("n'écrivent aucune couleur en dur", () => {
    for (const [file, css] of Object.entries(sheets)) {
      const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
      expect(code, file).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(code, file).not.toMatch(/\b(rgb|rgba|hsl|hsla)\(/);
    }
  });

  it("n'utilisent que les points de rupture déclarés", () => {
    const allowed = new Set(Object.values(BREAKPOINTS));
    for (const [file, css] of Object.entries(sheets)) {
      for (const match of css.matchAll(/min-width:\s*([\d.]+rem)/g)) {
        expect(allowed.has(match[1] as never), `${file} : ${match[1]}`).toBe(true);
      }
    }
  });

  it("donnent une zone tactile minimale aux éléments interactifs", () => {
    for (const name of ["IconButton", "MainNav", "ThemeSelector"]) {
      const file = Object.keys(sheets).find((path) => path.endsWith(`${name}.module.css`));
      expect(file, name).toBeDefined();
      expect(sheets[file as string], name).toContain("min-height: var(--tap-min)");
    }
  });
});
