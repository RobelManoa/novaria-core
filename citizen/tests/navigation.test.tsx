import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { ecrire, lire } from "../src/stockage";
import type { Trajet } from "../src/trajets";
import type { PublicAlert } from "../src/types";
import { alert, network } from "./fixtures";

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

function show(alertes: () => Promise<PublicAlert[]> = async () => []) {
  return render(
    <App
      fetcher={async () => network()}
      alertsFetcher={alertes}
      alertsIntervalMs={5_000}
      now={() => NOW}
    />,
  );
}
const avancer = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

describe("les onglets, les messages et les réglages", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    ecrire([GARE, CALME]);
  });
  afterEach(() => vi.useRealTimers());

  it("l'accueil et les messages ont une navigation du bas ; le détail et les réglages n'en ont pas", async () => {
    show();
    await screen.findByRole("region", { name: "Mes trajets" });
    const nav = screen.getByRole("navigation", { name: "Navigation principale" });
    expect(within(nav).getByRole("link", { name: "Mes trajets" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    await userEvent.click(within(nav).getByRole("link", { name: "Messages" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Messages" })).toHaveFocus();
    expect(
      within(screen.getByRole("navigation", { name: "Navigation principale" })).getByRole("link", {
        name: "Messages",
      }),
    ).toHaveAttribute("aria-current", "page");

    await userEvent.click(screen.getByRole("link", { name: "Mes trajets" }));
    await userEvent.click(await screen.findByRole("link", { name: "Aller à la gare" }));
    await screen.findByRole("article", { name: "Aller à la gare" });
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("les réglages s'ouvrent par la roue de l'accueil et se ferment par « Mes trajets »", async () => {
    show();
    await screen.findByRole("region", { name: "Mes trajets" });
    await userEvent.click(screen.getByRole("link", { name: "Réglages et confidentialité" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Réglages et confidentialité" }),
    ).toHaveFocus();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Données simulées"); // sur chaque écran

    const simule = screen.getByRole("region", { name: "Données simulées" });
    expect(simule).toHaveTextContent("toutes les 15 secondes");
    expect(simule).toHaveTextContent("toutes les 5 secondes");

    const mots = screen.getByRole("region", { name: "Comprendre les mots" });
    expect(within(mots).getAllByRole("listitem")).toHaveLength(5);
    expect(mots).toHaveTextContent("Information incomplète");

    const vie = screen.getByRole("region", { name: "Vos trajets restent chez vous" });
    expect(vie).toHaveTextContent("Sans compte, sans cookie.");
    expect(vie).toHaveTextContent("Jamais envoyés à un serveur.");

    await userEvent.click(screen.getByRole("link", { name: "Mes trajets" }));
    expect(await screen.findByRole("region", { name: "Mes trajets" })).toBeInTheDocument();
  });

  it("supprimer un trajet depuis les réglages le retire de la liste et de l'appareil", async () => {
    show();
    await screen.findByRole("region", { name: "Mes trajets" });
    await userEvent.click(screen.getByRole("link", { name: "Réglages et confidentialité" }));
    const liste = await screen.findByRole("region", { name: "Mes trajets (2)" });
    await userEvent.click(
      within(liste).getByRole("button", { name: "Supprimer le trajet Rue calme" }),
    );
    expect(await screen.findByRole("region", { name: "Mes trajets (1)" })).toBeInTheDocument();
    expect(lire().trajets?.map((t) => t.id)).toEqual(["t-gare"]);
  });

  it("sans trajet, les réglages ne proposent ni liste ni « Effacer »", async () => {
    window.localStorage.clear();
    show();
    await screen.findByRole("region", { name: "Des trajets pour essayer" });
    await userEvent.click(screen.getByRole("link", { name: "Réglages et confidentialité" }));
    await screen.findByRole("heading", { level: 1, name: "Réglages et confidentialité" });
    expect(screen.queryByRole("button", { name: "Effacer mes trajets" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^Mes trajets \(/ })).not.toBeInTheDocument();
  });

  it("l'écran « Messages » est vide, et le dit, tant qu'aucune alerte ne s'est ouverte", async () => {
    window.location.hash = "#/messages";
    show();
    expect(await screen.findByText("Aucun message pour l'instant")).toBeInTheDocument();
    expect(screen.getByText(/Vous êtes prévenu pour 1 trajet sur 2\./)).toBeInTheDocument();
    expect(screen.getByText(/ne sont gardés nulle part/)).toBeInTheDocument();
  });

  it("un message arrive : pastille « 1 » sur l'onglet, bandeau en haut ; l'ouvrir éteint les deux et le garde dans la liste", async () => {
    let courantes: PublicAlert[] = [];
    show(async () => courantes);
    await screen.findByRole("region", { name: "Mes trajets" });
    await avancer(100);
    courantes = [alert({ alert_id: "a1", road_segment_id: "ROAD_004", severity: "WARNING" })];
    await avancer(5_100);

    expect(await screen.findByRole("group", { name: "Message pour votre trajet" })).toBeVisible();
    const lien = screen.getByRole("link", { name: "Messages (1 nouveau)" });

    await userEvent.click(lien);
    const recus = await screen.findByRole("region", { name: "Reçus pendant cette visite" });
    const [message] = within(recus).getAllByRole("listitem");
    expect(message).toHaveTextContent("Aller à la gare : une alerte vient de s'ouvrir");
    expect(message).toHaveTextContent("Attention");
    expect(message).toHaveTextContent("Message simulé");
    expect(within(message).getByRole("link", { name: /Voir le trajet/ })).toHaveAttribute(
      "href",
      "#/trajet/t-gare",
    );
    // lu : plus de pastille, plus de bandeau, mais le message reste dans la liste
    expect(screen.getByRole("link", { name: "Messages" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Mes trajets" }));
    await screen.findByRole("region", { name: "Mes trajets" });
    expect(
      screen.queryByRole("group", { name: "Message pour votre trajet" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Messages" })).toBeInTheDocument();
  });

  it("« Fermer » le bandeau marque le message lu sans le supprimer de la liste", async () => {
    let courantes: PublicAlert[] = [];
    show(async () => courantes);
    await screen.findByRole("region", { name: "Mes trajets" });
    await avancer(100);
    courantes = [alert({ alert_id: "a1", road_segment_id: "ROAD_004" })];
    await avancer(5_100);
    const bandeau = await screen.findByRole("group", { name: "Message pour votre trajet" });
    await userEvent.click(within(bandeau).getByRole("button", { name: "Fermer" }));
    expect(
      screen.queryByRole("group", { name: "Message pour votre trajet" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Messages" }));
    const recus = await screen.findByRole("region", { name: "Reçus pendant cette visite" });
    expect(within(recus).getAllByRole("listitem")).toHaveLength(1);
  });

  it("« Me prévenir, trajet par trajet » se règle depuis les messages et reste gardé", async () => {
    window.location.hash = "#/messages";
    show();
    const section = await screen.findByRole("region", { name: "Me prévenir, trajet par trajet" });
    const calme = within(section).getByRole("checkbox", { name: "Me prévenir pour Rue calme" });
    expect(calme).not.toBeChecked();
    await userEvent.click(calme);
    expect(calme).toBeChecked();
    expect(lire().trajets?.find((t) => t.id === "t-calme")?.prevenir).toBe(true);
    expect(screen.getByText(/Vous êtes prévenu pour 2 trajets sur 2\./)).toBeInTheDocument();
  });

  it("sans trajet, les messages le disent et ne proposent aucun réglage", async () => {
    window.localStorage.clear();
    window.location.hash = "#/messages";
    show();
    expect(
      await screen.findByText(/Vous n'avez pas encore de trajet à suivre\./),
    ).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("passe l'audit d'accessibilité (WCAG 2.1 AA) : messages vides, avec un message, réglages", async () => {
    const options = {
      runOnly: {
        type: "tag" as const,
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
      },
      rules: { "color-contrast": { enabled: false } },
    };
    let courantes: PublicAlert[] = [];
    window.location.hash = "#/messages";
    show(async () => courantes);
    await screen.findByText("Aucun message pour l'instant");
    expect((await axe.run(document.body, options)).violations.map((v) => v.id)).toEqual([]);

    courantes = [alert({ alert_id: "a1", road_segment_id: "ROAD_004" })];
    await avancer(5_100);
    await screen.findByRole("region", { name: "Reçus pendant cette visite" });
    await screen.findAllByRole("listitem");
    expect((await axe.run(document.body, options)).violations.map((v) => v.id)).toEqual([]);

    window.location.hash = "#/reglages";
    await screen.findByRole("heading", { level: 1, name: "Réglages et confidentialité" });
    expect((await axe.run(document.body, options)).violations.map((v) => v.id)).toEqual([]);
  });
});
