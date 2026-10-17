import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../src/app/App";

describe("App", () => {
  afterEach(() => vi.restoreAllMocks());

  it("affiche la version de l'API quand elle répond", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ status: "ok", version: "0.1.0", revision: "abc123", environment: "test" }),
      ),
    );
    render(<App />);
    expect(await screen.findByRole("status")).toHaveTextContent("abc123");
  });

  it("affiche une erreur quand l'API est indisponible", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 503 }));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("503");
  });
});
