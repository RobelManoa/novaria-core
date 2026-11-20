import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, CONGESTION_PATH, fetchCongestion } from "../src/api";
import { network, segment } from "./fixtures";

function reponse(corps: unknown, init: ResponseInit = { status: 200 }): Response {
  return new Response(typeof corps === "string" ? corps : JSON.stringify(corps), init);
}

function simule(valeur: Response | Error | DOMException) {
  const appel = vi.fn<typeof fetch>(async () => {
    if (valeur instanceof Response) return valeur;
    throw valeur;
  });
  vi.stubGlobal("fetch", appel);
  return appel;
}

afterEach(() => vi.unstubAllGlobals());

describe("appel de l'API publique", () => {
  it("ne lit que la route publique de congestion, sans jeton, sans cookie, sans autre en-tête que Accept", async () => {
    const appel = simule(reponse({ items: network() }));
    await fetchCongestion();
    expect(appel).toHaveBeenCalledTimes(1);
    const [adresse, options] = appel.mock.calls[0];
    expect(adresse).toBe("/api/v1/public/congestion");
    expect(CONGESTION_PATH).toBe("/api/v1/public/congestion");
    expect(options?.method).toBe("GET");
    expect(options?.credentials).toBe("omit");
    expect(options?.headers).toEqual({ Accept: "application/json" });
    expect(options?.body).toBeUndefined();
  });

  it("rend les tronçons tels que l'API les a envoyés", async () => {
    simule(reponse({ items: network() }));
    expect(await fetchCongestion()).toEqual(network());
  });

  it("accepte une liste vide : ce n'est pas une erreur", async () => {
    simule(reponse({ items: [] }));
    expect(await fetchCongestion()).toEqual([]);
  });

  it("peut viser une autre base d'adresse (tests, aperçu)", async () => {
    const appel = simule(reponse({ items: [] }));
    await fetchCongestion(undefined, "http://passerelle");
    expect(appel.mock.calls[0][0]).toBe("http://passerelle/api/v1/public/congestion");
  });

  it.each([
    [429, "limite"],
    [500, "indisponible"],
    [503, "indisponible"],
    [404, "indisponible"],
    [418, "inattendue"],
    [401, "inattendue"],
  ])("le code HTTP %i est classé « %s »", async (status, kind) => {
    simule(reponse({}, { status }));
    await expect(fetchCongestion()).rejects.toMatchObject({ name: "ApiError", kind });
  });

  it("un réseau coupé est une erreur « reseau »", async () => {
    simule(new TypeError("Failed to fetch"));
    await expect(fetchCongestion()).rejects.toMatchObject({ kind: "reseau" });
  });

  it("une annulation n'est pas une erreur de l'API : elle est relancée telle quelle", async () => {
    simule(new DOMException("annulé", "AbortError"));
    const erreur = await fetchCongestion().catch((e: unknown) => e);
    expect(erreur).toBeInstanceOf(DOMException);
    expect((erreur as DOMException).name).toBe("AbortError");
    expect(erreur).not.toBeInstanceOf(ApiError);
  });

  it.each([
    ["un corps illisible", "<html>"],
    ["un corps qui n'est pas un objet", "[]"],
    ["un corps sans items", "{}"],
    ["items qui n'est pas une liste", '{"items": 3}'],
    ["un champ en plus dans la réponse", JSON.stringify({ items: [], extra: 1 })],
    ["un tronçon sans champ", JSON.stringify({ items: [{ ...segment(), simulated: undefined }] })],
    [
      "un tronçon avec un champ de plus",
      JSON.stringify({ items: [{ ...segment(), vehicle_count: 3 }] }),
    ],
    ["un état inconnu", JSON.stringify({ items: [segment({ state: "JAMMED" as never })] })],
    ["un côté inconnu", JSON.stringify({ items: [segment({ approach: "X" as never })] })],
    ["une date impossible", JSON.stringify({ items: [segment({ updated_at: "pas une date" })] })],
    [
      "un simulated qui n'est pas un booléen",
      JSON.stringify({ items: [{ ...segment(), simulated: "oui" }] }),
    ],
  ])("%s est une erreur de format, pas une donnée", async (_titre, corps) => {
    simule(reponse(corps));
    await expect(fetchCongestion()).rejects.toMatchObject({ name: "ApiError", kind: "format" });
  });

  it("l'erreur ne contient ni adresse, ni corps, ni détail technique", async () => {
    simule(reponse({ detail: "secret interne postgresql://u:p@h" }, { status: 500 }));
    const erreur = await fetchCongestion().catch((e: unknown) => e);
    expect(erreur).toBeInstanceOf(ApiError);
    expect(String((erreur as ApiError).message)).not.toMatch(/postgresql|secret|http/i);
  });
});
