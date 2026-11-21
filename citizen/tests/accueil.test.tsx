import { render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../src/App";
import { ecrire } from "../src/stockage";
import type { Trajet } from "../src/trajets";
import { resumeDesTrajets } from "../src/verdict";
import { network } from "./fixtures";

const NOW = Date.parse("2026-11-20T09:12:00Z");

const GARE: Trajet = {
  id: "t-gare",
  nom: "Aller à la gare",
  troncons: ["ROAD_001", "ROAD_004"],
  prevenir: true,
};
const CALME: Trajet = {
  id: "t-calme",
  nom: "Rue calme",
  troncons: ["ROAD_003", "ROAD_004"],
  prevenir: false,
};
const LENT: Trajet = { id: "t-lent", nom: "Trajet lent", troncons: ["ROAD_002"], prevenir: false };
const VIDE: Trajet = { id: "t-vide", nom: "Sans mesure", troncons: ["ROAD_020"], prevenir: false };

const show = () =>
  render(<App fetcher={async () => network()} alertsFetcher={async () => []} now={() => NOW} />);

describe("l'accueil : le résumé de mes trajets", () => {
  it("compte les trajets par verdict, le plus grave d'abord, sans les zéros", () => {
    const parId = new Map(network().map((s) => [s.road_segment_id, s] as const));
    expect(resumeDesTrajets([GARE, CALME, LENT, VIDE, { ...CALME, id: "autre" }], parId)).toEqual([
      { verdict: "BLOQUE", n: 1 },
      { verdict: "RALENTI", n: 1 },
      { verdict: "INDISPONIBLE", n: 1 },
      { verdict: "LIBRE", n: 2 },
    ]);
    expect(resumeDesTrajets([], parId)).toEqual([]);
  });
});

describe("l'accueil : l'écran", () => {
  beforeEach(() => window.localStorage.clear());

  it("avec des trajets gardés : un titre, le résumé, des cartes qui sont des liens, rien d'autre à régler", async () => {
    ecrire([GARE, CALME, LENT]);
    show();
    const region = await screen.findByRole("region", { name: "Mes trajets" });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Mes trajets");

    const resume = screen.getByRole("region", { name: "En ce moment" });
    expect(
      within(resume)
        .getAllByRole("listitem")
        .map((l) => l.textContent),
    ).toEqual(["1 bloqué", "1 ralenti", "1 libre"]);

    const gare = within(region).getByRole("listitem", { name: "Aller à la gare" });
    expect(within(gare).getByRole("link", { name: "Aller à la gare" })).toHaveAttribute(
      "href",
      "#/trajet/t-gare",
    );
    expect(gare).toHaveTextContent("Je suis prévenu");
    expect(within(region).getByRole("listitem", { name: "Rue calme" })).not.toHaveTextContent(
      "Je suis prévenu",
    );

    // La carte ne porte plus de réglage : « Me prévenir » et « Supprimer » sont dans le détail.
    expect(within(region).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(within(region).queryByRole("button", { name: /Supprimer/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Voir chaque tronçon du trajet")).not.toBeInTheDocument();
    expect(screen.queryByText("Trois mots à retenir")).not.toBeInTheDocument();
  });

  it("à la première ouverture : la question, les trois mots, des exemples à garder", async () => {
    show();
    const region = await screen.findByRole("region", { name: "Des trajets pour essayer" });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Votre route est-elle libre ?",
    );
    const mots = screen.getByRole("region", { name: "Trois mots à retenir" });
    expect(
      within(mots)
        .getAllByRole("listitem")
        .map((l) => l.textContent),
    ).toEqual([
      "LibreVous pouvez partir.",
      "RalentiPrévoyez un peu de retard.",
      "BloquéPrévoyez beaucoup de retard.",
    ]);
    expect(within(region).getAllByRole("button", { name: "Garder ce trajet" })).toHaveLength(3);
    expect(within(region).queryByRole("link")).not.toBeInTheDocument(); // un exemple n'a pas encore de détail
    expect(screen.queryByRole("region", { name: "En ce moment" })).not.toBeInTheDocument();
  });

  it("dit toujours « Données simulées » en haut, et la phrase complète en bas", async () => {
    ecrire([GARE]);
    show();
    await screen.findByRole("region", { name: "Mes trajets" });
    expect(screen.getByRole("note")).toHaveTextContent("Données simulées");
    expect(screen.getByRole("contentinfo")).toHaveTextContent(
      "ne décrivent pas la circulation réelle",
    );
  });

  it("passe l'audit d'accessibilité (WCAG 2.1 AA), première ouverture comme trajets gardés", async () => {
    for (const trajets of [[], [GARE, CALME, LENT, VIDE]]) {
      window.localStorage.clear();
      if (trajets.length > 0) ecrire(trajets);
      const vue = show();
      await screen.findByRole("region", { name: /trajets/i });
      const resultat = await axe.run(document.body, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
        rules: { "color-contrast": { enabled: false } },
      });
      expect(resultat.violations.map((v) => v.id)).toEqual([]);
      vue.unmount();
    }
  });
});
