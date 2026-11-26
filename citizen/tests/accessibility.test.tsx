import { render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../src/App";
import { ApiError } from "../src/api";
import type { PublicAlert, SegmentState } from "../src/types";
import { network, ouvrirDetail } from "./fixtures";

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
    render(
      <App alertsFetcher={async () => []} fetcher={() => new Promise<SegmentState[]>(() => {})} />,
    );
    expect(await audit()).toEqual([]);
  });

  it("vue principale", async () => {
    render(<App alertsFetcher={async () => []} fetcher={async () => network()} />);
    await screen.findByRole("region", { name: /trajets/i });
    expect(await audit()).toEqual([]);
  });

  it("liste vide", async () => {
    render(<App alertsFetcher={async () => []} fetcher={async () => []} />);
    await screen.findByRole("region", { name: /trajets/i });
    expect(await audit()).toEqual([]);
  });

  it("erreur sans donnée", async () => {
    render(
      <App
        alertsFetcher={async () => []}
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
        alertsFetcher={async () => []}
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

describe("accessibilité de « Mes trajets » (ADR-031)", () => {
  beforeEach(() => window.localStorage.clear());

  it("un trajet gardé, « Me prévenir » activé, le détail ouvert et un message simulé", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const { alert } = await import("./fixtures");
    let courantes: PublicAlert[] = [];
    render(
      <App
        fetcher={async () => network()}
        alertsFetcher={async () => courantes}
        alertsIntervalMs={20}
      />,
    );
    const region = await screen.findByRole("region", { name: /trajets/i });
    await userEvent.click(
      within(within(region).getByRole("listitem", { name: "Aller à la gare" })).getByRole(
        "button",
        { name: "Garder ce trajet" },
      ),
    );
    await ouvrirDetail("Aller à la gare");
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }),
    );
    expect(await audit()).toEqual([]);
    courantes = [alert({ alert_id: "m1", road_segment_id: "ROAD_004", severity: "CRITICAL" })];
    await screen.findByRole("group", { name: "Message pour votre trajet" });
    expect(await audit()).toEqual([]);
  });

  it("le formulaire d'ajout d'un trajet, avec son message d'erreur", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    render(<App alertsFetcher={async () => []} fetcher={async () => network()} />);
    await screen.findByRole("region", { name: /trajets/i });
    await userEvent.click(screen.getByRole("link", { name: "Ajouter un trajet" }));
    expect(await audit()).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ce trajet" }));
    await screen.findByRole("alert");
    expect(await audit()).toEqual([]);
  });

  it("« Me prévenir » avec le service des alertes en panne", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    render(
      <App
        fetcher={async () => network()}
        alertsFetcher={async () => {
          throw new ApiError("indisponible", "x");
        }}
      />,
    );
    const region = await screen.findByRole("region", { name: /trajets/i });
    await userEvent.click(
      within(within(region).getByRole("listitem", { name: "Aller à la gare" })).getByRole(
        "button",
        { name: "Garder ce trajet" },
      ),
    );
    await ouvrirDetail("Aller à la gare");
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }),
    );
    await screen.findByText(/ne se met plus à jour/);
    expect(await audit()).toEqual([]);
  });
});
