import { act, screen } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import { findEnglish } from "../../scripts/audit-francais.mjs";
import indexHtml from "../../index.html?raw";
import { ALERT } from "../fixtures/alerts";
import { renderApp } from "../utils/renderApp";

// Garde-fou de CI de l'audit d'accessibilité (FE-07, EXG-NFR-15). Le vrai audit, dans un navigateur (contrastes,
// clavier, thèmes), est `npm run a11y:audit` ; ici axe-core tourne dans jsdom : il voit la structure (noms,
// rôles, libellés, titres, repères) mais pas les couleurs, car jsdom ne calcule pas le rendu. Chaque page est
// aussi relue à la recherche de textes en anglais.

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
const REPORT = {
  report_id: "3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d00",
  title: "Rapport de supervision du 20/10/2026",
  period_start: "2026-10-20T00:00:00Z",
  period_end: "2026-10-20T23:59:59Z",
  generated_at: "2026-10-20T23:30:00Z",
  file_name: "rapport-2026-10-20.pdf",
  size_bytes: 123_456,
  content_type: "application/pdf",
  sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
};

type Api = Record<string, (request: Request) => Response | Promise<Response>>;

const PAGES: Array<{ name: string; path: string; signedIn?: boolean; api?: Api }> = [
  { name: "connexion", path: "/connexion", signedIn: false },
  { name: "tableau de bord", path: "/" },
  {
    name: "alertes",
    path: "/alertes",
    api: { "GET /api/v1/alerts": () => json({ items: [ALERT], next_cursor: null }) },
  },
  { name: "feux de circulation", path: "/feux" },
  { name: "prévisions", path: "/previsions" },
  {
    name: "rapports",
    path: "/rapports",
    api: { "GET /api/v1/reports": () => json({ items: [REPORT], next_cursor: null }) },
  },
  { name: "page introuvable", path: "/inexistant" },
];

/** Tout le texte vu par un utilisateur ou un lecteur d'écran : texte affiché et noms accessibles. */
function readableTexts(): string[] {
  const texts: string[] = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent?.replace(/\s+/g, " ").trim();
    if (text) texts.push(text);
  }
  for (const element of document.querySelectorAll("[aria-label],[title],[placeholder],img[alt]")) {
    for (const name of ["aria-label", "title", "placeholder", "alt"]) {
      const value = element.getAttribute(name);
      if (value) texts.push(value);
    }
  }
  return texts;
}

describe.each(PAGES)("accessibilité de la page $name", ({ path, signedIn, api }) => {
  async function show() {
    renderApp(path, { signedIn: signedIn ?? true, api });
    await screen.findByRole("heading", { level: 1 });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 60));
    });
  }

  it("n'a aucune violation WCAG A ou AA ni bonne pratique d'axe (hors couleurs)", async () => {
    await show();
    const results = await axe.run(document.body, {
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"],
      },
      // jsdom ne calcule ni couleurs ni mise en page : le contraste est mesuré par l'audit dans un navigateur.
      rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
    });
    const summary = results.violations.map(
      (v) => `${v.id} : ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
    );
    expect(summary).toEqual([]);
  });

  it("n'affiche aucun texte en anglais", async () => {
    await show();
    expect(findEnglish(readableTexts())).toEqual([]);
  });
});

describe("langue du document", () => {
  it("est déclarée en français dans index.html (le test n'a pas de vrai document : lu dans le fichier)", () => {
    expect(indexHtml).toMatch(/<html[^>]*\slang="fr"/);
    expect(findEnglish(["lang=fr"])).toEqual([]);
    expect(findEnglish(["lang=en"])).not.toEqual([]);
  });
});
