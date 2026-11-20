import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import App from "../src/App";
import { ApiError } from "../src/api";
import type { SegmentState } from "../src/types";
import { network } from "./fixtures";

/**
 * Audit automatique (axe-core, règles WCAG 2.0, 2.1 et 2.2 de niveaux A et AA) de chaque état de l'écran. Le contraste n'est pas
 * calculable sans moteur de rendu : il est prouvé à part, sur les couleurs du fichier de styles (contrast.test.ts).
 * Un audit automatique ne remplace pas un essai avec un lecteur d'écran : il attrape une partie des défauts, pas tous.
 */
const OPTIONS = {
  runOnly: {
    type: "tag" as const,
    values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
  },
  rules: { "color-contrast": { enabled: false } },
};

async function audit() {
  const resultat = await axe.run(document.body, OPTIONS);
  return resultat.violations.map(
    (v) => `${v.id} : ${v.nodes.map((n) => n.html.slice(0, 80)).join(" | ")}`,
  );
}

describe("accessibilité de chaque état (WCAG 2.1 AA)", () => {
  it("chargement", async () => {
    render(<App fetcher={() => new Promise<SegmentState[]>(() => {})} />);
    expect(await audit()).toEqual([]);
  });

  it("vue principale", async () => {
    render(<App fetcher={async () => network()} />);
    await screen.findByRole("region", { name: "En un coup d'œil" });
    expect(await audit()).toEqual([]);
  });

  it("liste vide", async () => {
    render(<App fetcher={async () => []} />);
    await screen.findByText("Aucune information pour le moment");
    expect(await audit()).toEqual([]);
  });

  it("erreur sans donnée", async () => {
    render(
      <App
        fetcher={async () => {
          throw new ApiError("reseau", "x");
        }}
      />,
    );
    await screen.findByRole("alert");
    expect(await audit()).toEqual([]);
  });

  it("erreur après un succès", async () => {
    let appels = 0;
    render(
      <App
        intervalMs={5}
        fetcher={async () => {
          appels += 1;
          if (appels === 1) return network();
          throw new ApiError("indisponible", "x");
        }}
      />,
    );
    await screen.findByText(/Mise à jour impossible/);
    expect(await audit()).toEqual([]);
  });
});

describe("page d'accueil", () => {
  const index = readFileSync(resolve(process.cwd(), "index.html"), "utf8");

  it("est en français, adaptée au téléphone, et ne bloque pas l'agrandissement", () => {
    expect(index).toMatch(/<html lang="fr">/);
    expect(index).toMatch(/name="viewport" content="width=device-width, initial-scale=1\.0"/);
    expect(index).not.toMatch(/user-scalable|maximum-scale/);
    expect(index).toMatch(/<title>[^<]+<\/title>/);
  });
});
