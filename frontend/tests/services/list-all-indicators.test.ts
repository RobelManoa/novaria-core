import { afterEach, describe, expect, it, vi } from "vitest";
import { listAllIndicators } from "@/services/traitement";

function indicator(id: string) {
  return { indicator_id: id };
}

/** Une réponse de page : `next` est le curseur de la page suivante, `null` sur la dernière. */
function page(ids: string[], next: string | null) {
  return new Response(JSON.stringify({ items: ids.map(indicator), next_cursor: next }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("listAllIndicators", () => {
  afterEach(() => vi.restoreAllMocks());

  it("suit les curseurs jusqu'à la dernière page, dans l'ordre reçu", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(page(["a", "b"], "c1"))
      .mockResolvedValueOnce(page(["c"], "c2"))
      .mockResolvedValueOnce(page(["d"], null));

    const result = await listAllIndicators({ window_size_s: 60, limit: 2 }, 10);

    expect(result.items.map((item) => item.indicator_id)).toEqual(["a", "b", "c", "d"]);
    expect(result.truncated).toBe(false);
    const urls = spy.mock.calls.map(([request]) => new URL((request as Request).url));
    expect(urls.map((url) => url.searchParams.get("cursor"))).toEqual([null, "c1", "c2"]);
    // Les filtres suivent chaque page.
    expect(urls.every((url) => url.searchParams.get("window_size_s") === "60")).toBe(true);
  });

  it("s'arrête à la limite de pages et le signale", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => page(["x"], "encore"));

    const result = await listAllIndicators({}, 3);

    expect(spy).toHaveBeenCalledTimes(3);
    expect(result.items).toHaveLength(3);
    expect(result.truncated).toBe(true);
  });

  it("ne marque pas comme tronquée une dernière page atteinte à la limite", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(page(["a"], "c1"))
      .mockResolvedValueOnce(page(["b"], null));

    const result = await listAllIndicators({}, 2);

    expect(result.truncated).toBe(false);
  });

  it("rend une liste vide quand l'API n'a rien", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(page([], null));

    expect(await listAllIndicators({}, 5)).toEqual({ items: [], truncated: false });
  });

  it("laisse passer l'erreur de l'API", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("{}", { status: 503 }));

    await expect(listAllIndicators({}, 5)).rejects.toMatchObject({ code: "UPSTREAM_UNAVAILABLE" });
  });
});
