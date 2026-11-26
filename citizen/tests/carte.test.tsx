import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../src/App";
import { compterEndroits, lieuLePlusGrave } from "../src/carte";
import { lienAjouter, lireRoute } from "../src/route";
import { lire } from "../src/stockage";
import type { PublicAlert, SegmentState } from "../src/types";
import { alert, network, segment } from "./fixtures";

const NOW = Date.parse("2026-11-20T09:12:00Z");
const carte = (map: SegmentState[]) => new Map(map.map((s) => [s.road_segment_id, s] as const));

function show(options: { donnees?: SegmentState[]; alertes?: () => Promise<PublicAlert[]> } = {}) {
  return render(
    <App
      fetcher={async () => options.donnees ?? network()}
      alertsFetcher={options.alertes ?? (async () => [])}
      now={() => NOW}
    />,
  );
}

describe("la carte : les règles", () => {
  it("compte les 24 endroits, un endroit absent de l'API étant « sans mesure »", () => {
    const n = compterEndroits(carte(network()));
    expect(n).toEqual({ FREE_FLOW: 3, SLOW: 1, CONGESTED: 1, UNKNOWN: 19 });
    expect(Object.values(n).reduce((a, b) => a + b, 0)).toBe(24);
    expect(compterEndroits(new Map())).toEqual({
      FREE_FLOW: 0,
      SLOW: 0,
      CONGESTED: 0,
      UNKNOWN: 24,
    });
  });

  it("met en avant la première place où l'état est le plus grave", () => {
    expect(lieuLePlusGrave(carte(network()))).toBe(0); // un tronçon bloqué à la Place de la Gare
    const marche = [
      segment({ road_segment_id: "ROAD_009", intersection_id: "INT_03", state: "CONGESTED" }),
    ];
    expect(lieuLePlusGrave(carte(marche))).toBe(2);
    expect(lieuLePlusGrave(new Map())).toBe(0);
  });

  it("l'adresse de l'ajout garde le rang de la place sans montrer aucun code", () => {
    expect(lienAjouter()).toBe("#/ajouter");
    expect(lienAjouter(2)).toBe("#/ajouter?lieu=3");
    expect(lireRoute("#/ajouter")).toEqual({ nom: "ajouter" });
    expect(lireRoute("#/ajouter?lieu=3")).toEqual({ nom: "ajouter", lieu: 2 });
    expect(lireRoute("#/carte")).toEqual({ nom: "carte" });
    for (const autre of [
      "#/ajouter?lieu=",
      "#/ajouter?lieu=a",
      "#/ajouter?lieu=123",
      "#/ajouter/x",
    ]) {
      expect(lireRoute(autre)).toEqual({ nom: "accueil" });
    }
  });
});

describe("la carte : l'écran", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "#/carte";
  });

  it("un résumé du réseau, le plan, la légende, la fiche de la place la plus grave", async () => {
    show();
    expect(await screen.findByRole("heading", { level: 1, name: "Carte du réseau" })).toBeVisible();

    const resume = await screen.findByRole("list", { name: "Résumé du réseau" });
    expect(
      within(resume)
        .getAllByRole("listitem")
        .map((l) => l.textContent),
    ).toEqual(["3Libres", "1Ralenti", "1Bloqué", "19Sans mesure"]);
  });

  it("le plan a six places ; la première est choisie, une autre se choisit d'un toucher", async () => {
    show();
    const plan = await screen.findByRole("region", { name: "Plan" });
    const places = within(plan).getAllByRole("button");
    expect(places).toHaveLength(6);
    expect(places[0]).toHaveAttribute("aria-pressed", "true");
    expect(places[0]).toHaveAccessibleName(
      /^Place de la Gare : en venant du nord bloqué, en venant de l'est ralenti/,
    );

    const fiche = screen.getByRole("region", { name: "Place de la Gare" });
    expect(fiche).toHaveTextContent("Grand axe · 2 voies · 300 m · limité à 50 km/h");
    expect(within(fiche).getAllByRole("listitem")).toHaveLength(4);
    expect(fiche).toHaveTextContent("En venant du nord");

    await userEvent.click(places[2] as HTMLElement);
    const marche = await screen.findByRole("region", { name: "Rue du Marché" });
    expect(marche).toHaveTextContent("Rue de liaison · 1 voie · 250 m · limité à 50 km/h");
    expect(places[2]).toHaveAttribute("aria-pressed", "true");
    expect(places[0]).toHaveAttribute("aria-pressed", "false");
    expect(
      within(marche).getByRole("link", { name: "Faire un trajet avec cette place" }),
    ).toHaveAttribute("href", "#/ajouter?lieu=3");
    expect(document.body.textContent).not.toMatch(/ROAD_|INT_/);
  });

  it("dit les alertes ouvertes, ou qu'il n'y en a aucune, ou qu'on ne sait pas", async () => {
    const premiere = show({
      alertes: async () => [
        alert({ road_segment_id: "ROAD_001", opened_at: "2026-11-20T09:08:30Z" }),
      ],
    });
    let section = await screen.findByRole("region", { name: "1 alerte en cours" });
    expect(section).toHaveTextContent("Place de la Gare, en venant du nord");
    expect(section).toHaveTextContent("il y a 3 min");
    expect(screen.getByRole("region", { name: "Place de la Gare" })).toHaveTextContent(
      "Alerte ouverte il y a 3 min",
    );
    premiere.unmount();

    const deuxieme = show();
    section = await screen.findByRole("region", { name: "Aucune alerte en cours" });
    expect(section).toBeVisible();
    deuxieme.unmount();

    show({ alertes: async () => Promise.reject(new TypeError("réseau")) });
    section = await screen.findByRole("region", { name: "Alertes" });
    await waitFor(() =>
      expect(section).toHaveTextContent("ne sont pas disponibles pour le moment"),
    );
  });

  it("l'onglet Carte est le courant, et la navigation a trois onglets", async () => {
    show();
    const nav = await screen.findByRole("navigation", { name: "Navigation principale" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual(["Mes trajets", "Carte", "Messages"]);
    expect(within(nav).getByRole("link", { name: "Carte" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("passe l'audit d'accessibilité (WCAG 2.1 AA)", async () => {
    show({ alertes: async () => [alert({ road_segment_id: "ROAD_001" })] });
    await screen.findByRole("region", { name: "Place de la Gare" });
    const r = await axe.run(document.body, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
    expect(r.violations.map((v) => `${v.id} ${v.nodes[0]?.html.slice(0, 80)}`)).toEqual([]);
  });
});

describe("ajouter un trajet : l'écran des croix", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "#/carte";
  });

  it("depuis la carte, « Faire un trajet avec cette place » ouvre l'ajout ; « Annuler » revient sans rien garder", async () => {
    show();
    await userEvent.click(
      await screen.findByRole("link", { name: "Faire un trajet avec cette place" }),
    );
    expect(
      await screen.findByRole("heading", { level: 1, name: "Ajouter un trajet" }),
    ).toHaveFocus();
    expect(window.location.hash).toBe("#/ajouter?lieu=1");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Annuler" }));
    expect(await screen.findByRole("region", { name: "Des trajets pour essayer" })).toBeVisible();
    expect(lire().trajets).toBeNull();
  });

  it("six places, quatre côtés chacune, la légende, aucun code à l'écran", async () => {
    window.location.hash = "#/ajouter";
    show();
    expect(await screen.findAllByRole("group")).toHaveLength(6);
    expect(screen.getAllByRole("button", { pressed: false })).toHaveLength(24);
    expect(
      within(screen.getByRole("list", { name: "Légende" })).getAllByRole("listitem"),
    ).toHaveLength(4);
    expect(document.body.textContent).not.toMatch(/ROAD_|INT_/);
  });

  it("toucher un côté le choisit, montre le verdict du trajet et permet de le retirer", async () => {
    window.location.hash = "#/ajouter";
    show();
    const nord = await screen.findByRole("button", {
      name: /^Place de la Gare, en venant du nord/,
    });
    expect(
      screen.getByRole("heading", { level: 2, name: "Votre trajet : 0 endroit" }),
    ).toBeVisible();
    await userEvent.click(nord);
    expect(nord).toHaveAttribute("aria-pressed", "true");
    const votre = screen.getByRole("region", { name: "Votre trajet : 1 endroit" });
    expect(votre).toHaveTextContent("Ce trajet est en ce moment");
    expect(votre).toHaveTextContent("Bloqué");

    await userEvent.click(
      screen.getByRole("button", { name: /^Place de la Gare, en venant de l'ouest/ }),
    );
    expect(screen.getByRole("region", { name: "Votre trajet : 2 endroits" })).toBeVisible();

    await userEvent.click(
      within(votre).getByRole("button", { name: /^Retirer Place de la Gare, en venant du nord/ }),
    );
    expect(nord).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("region", { name: "Votre trajet : 1 endroit" })).toHaveTextContent(
      "Libre",
    );
  });

  it("ajouter : le trajet est gardé avec son nom et « Me prévenir », et l'accueil le montre", async () => {
    window.location.hash = "#/ajouter";
    show();
    await userEvent.click(
      await screen.findByRole("button", { name: /^Place de la Gare, en venant du nord/ }),
    );
    await userEvent.type(screen.getByLabelText(/Nom du trajet/), "Chez moi au travail");
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ce trajet" }));

    const region = await screen.findByRole("region", { name: "Mes trajets" });
    const nouveau = within(region).getByRole("listitem", { name: "Chez moi au travail" });
    expect(nouveau).toHaveTextContent("Bloqué");
    expect(nouveau).toHaveTextContent("Je suis prévenu");
    expect(lire().trajets?.[0]).toMatchObject({
      nom: "Chez moi au travail",
      troncons: ["ROAD_001"],
      prevenir: true,
    });
  });

  it("passe l'audit d'accessibilité (WCAG 2.1 AA), vide et avec un trajet", async () => {
    window.location.hash = "#/ajouter";
    show();
    const options = {
      runOnly: {
        type: "tag" as const,
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
      },
      rules: { "color-contrast": { enabled: false } },
    };
    await screen.findAllByRole("group");
    expect((await axe.run(document.body, options)).violations.map((v) => v.id)).toEqual([]);
    await userEvent.click(
      screen.getByRole("button", { name: /^Place de la Gare, en venant du nord/ }),
    );
    await userEvent.click(
      screen
        .getByRole("button", { name: "Ajouter ce trajet" })
        .closest("form")!
        .querySelector("button[type=submit]")!,
    );
    expect((await axe.run(document.body, options)).violations.map((v) => v.id)).toEqual([]);
  });
});
