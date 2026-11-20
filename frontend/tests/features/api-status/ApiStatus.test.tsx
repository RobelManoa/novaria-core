import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ApiStatus from "@/features/api-status/ApiStatus";

describe("ApiStatus", () => {
  afterEach(() => vi.restoreAllMocks());

  it("affiche la version de l'API quand elle répond", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ status: "ok", version: "0.1.0", revision: "abc123", environment: "test" }),
      ),
    );
    render(<ApiStatus />);
    expect(await screen.findByRole("status")).toHaveTextContent("abc123");
  });

  it("affiche une erreur quand l'API est indisponible", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 503 }));
    render(<ApiStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent("503");
  });

  it("indique la vérification en cours avant la réponse", async () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    render(<ApiStatus />);
    expect(screen.getByText("Vérification de l'API…")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("dit que l'API est injoignable quand le réseau est coupé (pas de code HTTP)", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(<ApiStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "API injoignable : Le serveur est injoignable. Vérifiez la connexion.",
    );
  });
});
