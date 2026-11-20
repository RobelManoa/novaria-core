import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * WCAG 2.1 AA : 4,5:1 pour le texte, 3:1 pour les formes et les contours qui portent une information (1.4.3, 1.4.11).
 * Les paires viennent du fichier de styles lui-même, pas d'une copie : changer une couleur sans vérifier fait échouer ce test.
 */
const CSS = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

function variables(block: string): Record<string, string> {
  return Object.fromEntries(
    [...block.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{6});/g)].map((m) => [m[1], m[2]]),
  );
}

const clair = variables(
  CSS.slice(CSS.indexOf(":root {"), CSS.indexOf("@media (prefers-color-scheme: dark)")),
);
const sombre = variables(
  CSS.slice(CSS.indexOf("@media (prefers-color-scheme: dark)"), CSS.indexOf("* {")),
);

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function ratio(a: string, b: string): number {
  const [haut, bas] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (haut + 0.05) / (bas + 0.05);
}

const TEXTE: [string, string][] = [
  ["text", "bg"],
  ["text", "surface"],
  ["muted", "bg"],
  ["muted", "surface"],
  ["free", "free-bg"],
  ["slow", "slow-bg"],
  ["congested", "congested-bg"],
  ["unknown", "unknown-bg"],
  ["info", "info-bg"],
  ["primary-contrast", "primary"],
  ["primary", "bg"],
  ["congested", "surface"],
  ["text", "info-bg"],
  ["info", "surface"],
];
const FORMES: [string, string][] = [
  ["focus", "bg"],
  ["focus", "surface"],
  ["free", "surface"],
  ["slow", "surface"],
  ["congested", "surface"],
  ["unknown", "surface"],
  ["border-strong", "bg"],
  ["free", "free-bg"],
  ["slow", "slow-bg"],
  ["congested", "congested-bg"],
];

describe.each([
  ["clair", clair],
  ["sombre", sombre],
] as const)("thème %s", (_nom, theme) => {
  it("définit toutes les couleurs utilisées", () => {
    for (const nom of new Set([...TEXTE, ...FORMES].flat()))
      expect(theme[nom], nom).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it.each(TEXTE)("le texte %s sur %s fait au moins 4,5:1", (avant, arriere) => {
    expect(ratio(theme[avant], theme[arriere])).toBeGreaterThanOrEqual(4.5);
  });

  it.each(FORMES)("la forme %s sur %s fait au moins 3:1", (avant, arriere) => {
    expect(ratio(theme[avant], theme[arriere])).toBeGreaterThanOrEqual(3);
  });
});

describe("le calcul lui-même", () => {
  it("retrouve les valeurs de référence du W3C", () => {
    expect(ratio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(ratio("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
    expect(ratio("#ffffff", "#ffffff")).toBe(1);
  });
});

describe("tailles et cibles", () => {
  it("le texte de base fait 16 px et aucune taille n'est écrite en pixels fixes", () => {
    expect(CSS).toMatch(/font:\s*1rem\/1\.5/);
    expect(CSS).not.toMatch(/font-size:\s*\d+px/);
  });

  it("les boutons font au moins 44 px de haut (2,75 rem)", () => {
    expect(CSS).toMatch(/--tap:\s*2\.75rem/);
    expect(CSS).toMatch(/\.bouton\s*\{[^}]*min-height:\s*var\(--tap\)/);
  });

  it("le focus est visible, la page peut être agrandie, l'animation respecte la préférence de réduction", () => {
    expect(CSS).toMatch(/:focus-visible\s*\{[^}]*outline:\s*3px/);
    expect(CSS).not.toMatch(/user-scalable|maximum-scale/);
    expect(CSS).toMatch(/prefers-reduced-motion:\s*reduce/);
  });
});
