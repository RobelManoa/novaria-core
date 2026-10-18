import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockHealth } from "./utils/renderApp";

describe("démarrage de l'application", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    document.body.innerHTML = "";
  });

  it("monte l'application dans #root et applique le thème mémorisé", async () => {
    mockHealth();
    window.localStorage.setItem("novaria-theme", "dark");
    document.body.innerHTML = '<div id="root"></div>';

    await import("@/main");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Tableau de bord" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Navigation principale" })).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });
});
