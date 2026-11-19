import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ScrollRegion from "@/components/ScrollRegion";
import globalCss from "@/styles/global.css?raw";
import { ALERT } from "../fixtures/alerts";
import { renderApp } from "../utils/renderApp";

// Défauts trouvés par l'audit dans un navigateur (FE-07) que jsdom ne peut pas voir lui-même : on garde donc
// la cause, pas l'effet. Chaque test échoue si le correctif est retiré.

describe("zone qui défile", () => {
  it("reçoit le focus au clavier et porte un nom (WCAG 2.1.1, règle axe scrollable-region-focusable)", () => {
    render(
      <ScrollRegion label="Un tableau large">
        <p>contenu</p>
      </ScrollRegion>,
    );
    const region = screen.getByRole("region", { name: "Un tableau large" });
    expect(region).toHaveAttribute("tabindex", "0");
    region.focus();
    expect(region).toHaveFocus();
  });

  it("entoure chaque tableau de l'application (alertes)", async () => {
    renderApp("/alertes", {
      api: {
        "GET /api/v1/alerts": () =>
          new Response(JSON.stringify({ items: [ALERT], next_cursor: null }), { status: 200 }),
      },
    });
    const region = await screen.findByRole("region", {
      name: "Alertes, de la plus récente à la plus ancienne",
    });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).getByRole("table")).toBeInTheDocument();
  });
});

describe("mouvement réduit", () => {
  it("coupe les transitions à 0 s, jamais à « presque 0 »", () => {
    const block =
      /prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\n\}/.exec(globalCss)?.[1] ?? "";
    // Une transition de 0,01 ms démarre à l'ancienne valeur : le tiroir de navigation restait en
    // visibility: hidden quand le focus devait y entrer, et le clavier perdait le focus (vu dans Edge).
    expect(block).toMatch(/transition-duration:\s*0s\s*!important/);
    expect(block).toMatch(/transition-delay:\s*0s\s*!important/);
    expect(block).not.toMatch(/transition-duration:\s*0\.01ms/);
  });
});
