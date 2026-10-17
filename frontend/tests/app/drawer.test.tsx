import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setViewportWidth } from "../matchMedia";
import { renderApp } from "../utils/renderApp";

const menuButton = () => within(screen.getByRole("banner")).getByRole("button", { name: /menu/i });
const nav = () => document.getElementById("navigation-principale") as HTMLElement;
const link = (name: string) => within(nav()).getByRole("link", { name });

describe("tiroir de navigation sur téléphone", () => {
  beforeEach(() => setViewportWidth(360));
  afterEach(() => vi.restoreAllMocks());

  it("est fermé au départ : bouton « Ouvrir le menu », navigation inerte", () => {
    renderApp();
    expect(menuButton()).toHaveAccessibleName("Ouvrir le menu");
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
    expect(menuButton()).toHaveAttribute("aria-controls", "navigation-principale");
    expect(nav()).toHaveAttribute("inert");
    expect(screen.queryByTestId("voile")).not.toBeInTheDocument();
  });

  it("s'ouvre au bouton : état annoncé, focus sur le premier lien, fond inerte, défilement bloqué", async () => {
    renderApp();
    await userEvent.click(menuButton());

    expect(menuButton()).toHaveAccessibleName("Fermer le menu");
    expect(menuButton()).toHaveAttribute("aria-expanded", "true");
    expect(nav()).not.toHaveAttribute("inert");
    expect(link("Tableau de bord")).toHaveFocus();
    expect(screen.getByRole("main")).toHaveAttribute("inert");
    expect(screen.getByRole("contentinfo")).toHaveAttribute("inert");
    expect(screen.getByRole("banner")).toHaveAttribute("inert");
    expect(document.body).toHaveClass("scroll-locked");
    expect(screen.getByTestId("voile")).toBeInTheDocument();
  });

  async function openDrawer() {
    const view = renderApp();
    await userEvent.click(menuButton());
    return view;
  }

  function expectClosedWithFocusOnButton() {
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
    expect(menuButton()).toHaveAccessibleName("Ouvrir le menu");
    expect(nav()).toHaveAttribute("inert");
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
    expect(document.body).not.toHaveClass("scroll-locked");
    expect(menuButton()).toHaveFocus();
  }

  it("se ferme avec Échap et rend le focus au bouton", async () => {
    await openDrawer();
    await userEvent.keyboard("{Escape}");
    expectClosedWithFocusOnButton();
  });

  it("se ferme au clic sur le voile et rend le focus au bouton", async () => {
    await openDrawer();
    await userEvent.click(screen.getByTestId("voile"));
    expectClosedWithFocusOnButton();
    expect(screen.queryByTestId("voile")).not.toBeInTheDocument();
  });

  it("se ferme avec son propre bouton de fermeture", async () => {
    await openDrawer();
    await userEvent.click(within(nav()).getByRole("button", { name: "Fermer le menu" }));
    expectClosedWithFocusOnButton();
  });

  it("se ferme au changement de page et place le focus sur le titre de la nouvelle page", async () => {
    await openDrawer();
    await userEvent.click(link("Alertes"));

    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
    expect(nav()).toHaveAttribute("inert");
    expect(document.body).not.toHaveClass("scroll-locked");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Alertes");
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });

  it("se ferme quand la navigation change par l'historique du navigateur", async () => {
    const { router } = renderApp("/alertes");
    await userEvent.click(menuButton());
    expect(menuButton()).toHaveAttribute("aria-expanded", "true");

    await act(() => router.navigate("/rapports"));
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
    expect(nav()).toHaveAttribute("inert");
  });

  it("se ferme quand la fenêtre repasse en largeur ordinateur", async () => {
    await openDrawer();
    setViewportWidth(1280);
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
    expect(nav()).not.toHaveAttribute("inert");
    expect(screen.queryByTestId("voile")).not.toBeInTheDocument();
    expect(document.body).not.toHaveClass("scroll-locked");

    setViewportWidth(360);
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
  });

  it("garde le focus dans le tiroir avec Tab et Maj+Tab", async () => {
    await openDrawer();
    const close = within(nav()).getByRole("button", { name: "Fermer le menu" });
    const last = link("Rapports");

    last.focus();
    await userEvent.tab();
    expect(close).toHaveFocus();

    await userEvent.tab({ shift: true });
    expect(last).toHaveFocus();
  });
});

describe("navigation sur ordinateur (largeur ≥ 64rem)", () => {
  it("affiche la barre latérale sans voile et sans fond inerte", () => {
    setViewportWidth(1280);
    renderApp();
    expect(nav()).not.toHaveAttribute("inert");
    expect(screen.queryByTestId("voile")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
  });

  it("ouvre le tiroir sous la largeur ordinateur (1000 px)", async () => {
    setViewportWidth(1000);
    renderApp();
    expect(nav()).toHaveAttribute("inert");
    await userEvent.click(menuButton());
    expect(menuButton()).toHaveAttribute("aria-expanded", "true");
  });
});
