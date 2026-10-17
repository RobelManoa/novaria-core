import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { routes } from "@/app/router";
import { NAV_ENTRIES } from "@/features/navigation/entries";
import { renderApp } from "../utils/renderApp";

const h1 = () => screen.getByRole("heading", { level: 1 });
const mainNav = () => screen.getByRole("navigation", { name: "Navigation principale" });

describe("navigation sur ordinateur", () => {
  afterEach(() => vi.restoreAllMocks());

  it("expose les repères sémantiques de la page", async () => {
    renderApp();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(mainNav()).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "contenu");
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    expect(await screen.findByRole("status")).toBeInTheDocument();
  });

  it("place le lien d'évitement en premier élément focalisable", async () => {
    renderApp();
    await userEvent.tab();
    const skip = screen.getByRole("link", { name: "Aller au contenu" });
    expect(skip).toHaveFocus();
    expect(skip).toHaveAttribute("href", "#contenu");
  });

  it("liste les cinq entrées du menu, la page d'accueil étant la page active", () => {
    renderApp();
    const links = within(mainNav()).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(NAV_ENTRIES.map((entry) => entry.label));
    expect(within(mainNav()).getByRole("link", { name: "Tableau de bord" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(mainNav()).getByRole("link", { name: "Alertes" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("ne déplace pas le focus et fixe le titre au premier chargement", () => {
    renderApp("/alertes");
    expect(document.title).toBe("Alertes · Novaria Core");
    expect(h1()).not.toHaveFocus();
  });

  it.each(NAV_ENTRIES)("« $label » mène à sa page ($path)", async ({ path, label }) => {
    const { router } = renderApp(path === "/" ? "/alertes" : "/");
    await userEvent.click(within(mainNav()).getByRole("link", { name: label }));

    expect(router.state.location.pathname).toBe(path);
    expect(h1()).toHaveTextContent(label);
    expect(h1()).toHaveFocus();
    expect(document.title).toBe(`${label} · Novaria Core`);
    expect(within(mainNav()).getByRole("link", { name: label })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText("Cette section sera disponible prochainement.")).toBeInTheDocument();
  });

  it("chaque entrée du menu correspond à une route titrée", () => {
    const children = routes[0].children ?? [];
    for (const entry of NAV_ENTRIES) {
      const route = children.find((child) =>
        entry.path === "/" ? child.index : `/${child.path}` === entry.path,
      );
      expect(route, entry.path).toBeDefined();
      expect((route?.handle as { title: string }).title).toBe(entry.label);
    }
  });

  it("affiche une page introuvable avec un lien de retour", async () => {
    const { router } = renderApp("/inexistant");
    expect(h1()).toHaveTextContent("Page introuvable");
    expect(document.title).toBe("Page introuvable · Novaria Core");

    await userEvent.click(screen.getByRole("link", { name: "Retour au tableau de bord" }));
    expect(router.state.location.pathname).toBe("/");
    expect(h1()).toHaveTextContent("Tableau de bord");
  });

  it("ne cite aucun numéro d'issue ni outil interne dans l'interface", () => {
    renderApp();
    expect(document.body.textContent).not.toMatch(/\b(FE|BE|DAT|IA|DOC)-\d+\b|#\d+|sonar|snyk/i);
  });
});
