import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { CLE, lire } from "../src/stockage";
import type { SegmentState } from "../src/types";
import { network, ouvrirDetail, segment } from "./fixtures";

const NOW = Date.parse("2026-11-20T09:12:00Z");

function show(donnees: SegmentState[] = network()) {
  return render(
    <App fetcher={async () => donnees} alertsFetcher={async () => []} now={() => NOW} />,
  );
}
const trajets = () => screen.findByRole("region", { name: /trajets/i });
const carte = (region: HTMLElement, nom: string) =>
  within(region).getByRole("listitem", { name: nom });

describe("mes trajets", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
  });
  afterEach(() => vi.restoreAllMocks());

  it("garder un trajet proposé le met dans « Mes trajets » et le garde sur l'appareil", async () => {
    show();
    const region = await trajets();
    await userEvent.click(
      within(carte(region, "Aller à la gare")).getByRole("button", { name: "Garder ce trajet" }),
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Mes trajets");
    expect(lire().trajets?.map((t) => t.nom)).toEqual(["Aller à la gare"]);
    expect(
      within(await trajets()).queryByRole("button", { name: "Garder ce trajet" }),
    ).not.toBeInTheDocument();
  });

  it("un trajet gardé est retrouvé à la réouverture, sans rien refaire", async () => {
    const premiere = show();
    await userEvent.click(
      within(carte(await trajets(), "Aller à la gare")).getByRole("button", {
        name: "Garder ce trajet",
      }),
    );
    premiere.unmount();
    show();
    const region = await trajets();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Mes trajets");
    expect(carte(region, "Aller à la gare")).toHaveTextContent("Bloqué");
    expect(within(region).queryByText("Aller au marché")).not.toBeInTheDocument(); // les exemples ne reviennent pas
  });

  it("ajouter son propre trajet : cocher des tronçons, nommer, valider", async () => {
    show();
    await trajets();
    await userEvent.click(screen.getByRole("link", { name: "Ajouter un trajet" }));
    await userEvent.click(
      screen.getByRole("button", { name: /^Avenue des Tilleuls, en venant du nord/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: /^Rue du Marché, en venant du sud/ }));
    await userEvent.type(screen.getByLabelText(/Nom du trajet/), "Chez moi au travail");
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ce trajet" }));
    const region = await trajets();
    const nouveau = carte(region, "Chez moi au travail");
    expect(nouveau).toHaveTextContent("Information indisponible"); // aucune mesure pour ces tronçons dans la fixture
    expect(lire().trajets?.[0].troncons).toEqual(["ROAD_005", "ROAD_011"]);
    expect(screen.queryByRole("form", { name: "Ajouter un trajet" })).not.toBeInTheDocument();
  });

  it("un trajet sans nom reçoit un nom lisible, jamais un code", async () => {
    show();
    await trajets();
    await userEvent.click(screen.getByRole("link", { name: "Ajouter un trajet" }));
    await userEvent.click(
      screen.getByRole("button", { name: /^Place de la Gare, en venant de l'est/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ce trajet" }));
    expect(lire().trajets?.[0].nom).toBe("Trajet par Place de la Gare");
  });

  it("refuse un trajet sans tronçon, et dit pourquoi en mots simples", async () => {
    show();
    await trajets();
    await userEvent.click(screen.getByRole("link", { name: "Ajouter un trajet" }));
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ce trajet" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choisissez au moins un tronçon.");
    expect(lire().trajets).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: /^Place de la Gare, en venant du nord/ }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("refuse plus de quatre tronçons", async () => {
    show();
    await trajets();
    await userEvent.click(screen.getByRole("link", { name: "Ajouter un trajet" }));
    for (const cote of ["du nord", "de l'est", "du sud", "de l'ouest"]) {
      await userEvent.click(
        screen.getByRole("button", { name: new RegExp(`^Place de la Gare, en venant ${cote}`) }),
      );
    }
    await userEvent.click(
      screen.getByRole("button", { name: /^Avenue des Tilleuls, en venant du nord/ }),
    ); // le cinquième
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ce trajet" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choisissez 4 tronçons au plus.");
    expect(lire().trajets).toBeNull();
  });

  it("annuler l'ajout ne garde rien", async () => {
    show();
    await trajets();
    await userEvent.click(screen.getByRole("link", { name: "Ajouter un trajet" }));
    await userEvent.click(
      screen.getByRole("button", { name: /^Place de la Gare, en venant du nord/ }),
    );
    await userEvent.click(screen.getByRole("link", { name: "Annuler" }));
    expect(
      screen.queryByRole("button", { name: /^Place de la Gare, en venant du nord/ }),
    ).not.toBeInTheDocument();
    expect(lire().trajets).toBeNull();
  });

  it("supprimer un trajet le retire de l'écran et de l'appareil", async () => {
    show();
    await userEvent.click(
      within(carte(await trajets(), "Aller à la gare")).getByRole("button", {
        name: "Garder ce trajet",
      }),
    );
    await ouvrirDetail("Aller à la gare");
    await userEvent.click(
      screen.getByRole("button", { name: "Supprimer le trajet Aller à la gare" }),
    );
    expect(lire().trajets).toEqual([]);
    expect(await trajets()).toHaveTextContent("Vous n'avez plus de trajet");
  });

  it("« Effacer mes trajets » fait tout disparaître et l'application redevient celle de la première visite", async () => {
    show();
    await userEvent.click(
      within(carte(await trajets(), "Aller à la gare")).getByRole("button", {
        name: "Garder ce trajet",
      }),
    );
    await userEvent.click(screen.getByRole("link", { name: "Réglages et confidentialité" }));
    await userEvent.click(await screen.findByRole("button", { name: "Effacer mes trajets" }));
    expect(window.localStorage.getItem(CLE)).toBeNull();
    expect(window.localStorage.length).toBe(0);
    expect(screen.queryByRole("button", { name: "Effacer mes trajets" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Mes trajets" }));
    expect(await trajets()).toHaveTextContent("Voici des exemples");
  });

  it("le verdict suit les données : Libre, Ralenti, Bloqué, avec la phrase qui aide à décider", async () => {
    show([
      segment({ road_segment_id: "ROAD_001", state: "FREE_FLOW" }),
      segment({ road_segment_id: "ROAD_004", state: "FREE_FLOW" }),
      segment({ road_segment_id: "ROAD_009", state: "SLOW" }),
      segment({ road_segment_id: "ROAD_010", state: "FREE_FLOW" }),
      segment({ road_segment_id: "ROAD_019", state: "CONGESTED" }),
      segment({ road_segment_id: "ROAD_020", state: "FREE_FLOW" }),
    ]);
    const region = await trajets();
    expect(carte(region, "Aller à la gare")).toHaveTextContent("Libre");
    expect(carte(region, "Aller à la gare")).toHaveTextContent("Vous pouvez partir.");
    expect(carte(region, "Aller au marché")).toHaveTextContent("Ralenti");
    expect(carte(region, "Aller au marché")).toHaveTextContent("prévoyez un peu de retard");
    expect(carte(region, "Déposer les enfants à l'école")).toHaveTextContent("Bloqué");
    expect(carte(region, "Déposer les enfants à l'école")).toHaveTextContent(
      "Là où ça se passe : Rue des Écoles, en venant du sud",
    );
  });

  it("le détail d'un trajet nomme chaque tronçon et dit son état en mots", async () => {
    show();
    await userEvent.click(
      within(carte(await trajets(), "Aller à la gare")).getByRole("button", {
        name: "Garder ce trajet",
      }),
    );
    const detail = await ouvrirDetail("Aller à la gare");
    const lignes = within(
      within(detail).getByRole("region", { name: "Où ça se passe" }),
    ).getAllByRole("listitem");
    expect(lignes[0]).toHaveTextContent("Place de la Gare, en venant du nord");
    expect(lignes[0]).toHaveTextContent("Bloqué");
    expect(lignes[1]).toHaveTextContent("Place de la Gare, en venant de l'ouest");
    expect(lignes[1]).toHaveTextContent("Libre");
  });

  it("sans stockage (mode privé), l'application marche et le dit", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("refusé", "SecurityError");
    });
    show();
    const region = await trajets();
    expect(screen.getByRole("contentinfo")).toHaveTextContent(
      "ne permet pas de garder vos trajets",
    );
    await userEvent.click(
      within(carte(region, "Aller à la gare")).getByRole("button", { name: "Garder ce trajet" }),
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Mes trajets"); // le trajet reste le temps de la page
  });

  it("une donnée illisible sur l'appareil est ignorée : on repart des trajets proposés", async () => {
    window.localStorage.setItem(CLE, "{pas du json");
    show();
    expect(await trajets()).toHaveTextContent("Des trajets pour essayer");
  });
});
