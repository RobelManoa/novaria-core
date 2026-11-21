import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CLE, VERSION, ecrire, effacer, lire } from "../src/stockage";
import type { Trajet } from "../src/trajets";

const trajet = (changes: Partial<Trajet> = {}): Trajet => ({
  id: "t-1",
  nom: "Aller à la gare",
  troncons: ["ROAD_001", "ROAD_004"],
  prevenir: false,
  ...changes,
});

describe("ce qui est gardé sur l'appareil du citoyen", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("rien n'est gardé à la première visite", () => {
    expect(lire()).toEqual({ trajets: null, disponible: true });
    expect(window.localStorage.length).toBe(0);
  });

  it("garde et relit des trajets, sous une seule clé", () => {
    expect(ecrire([trajet(), trajet({ id: "t-2", prevenir: true })])).toBe(true);
    expect(window.localStorage.length).toBe(1);
    expect(window.localStorage.key(0)).toBe(CLE);
    expect(lire().trajets).toEqual([trajet(), trajet({ id: "t-2", prevenir: true })]);
  });

  it("ne garde rien d'autre que les trajets et la version : ni date, ni identifiant de visiteur", () => {
    ecrire([trajet()]);
    const brut = JSON.parse(window.localStorage.getItem(CLE) ?? "null");
    expect(Object.keys(brut).sort()).toEqual(["trajets", "version"]);
    expect(Object.keys(brut.trajets[0]).sort()).toEqual(["id", "nom", "prevenir", "troncons"]);
    expect(brut.version).toBe(VERSION);
    expect(JSON.stringify(brut)).not.toMatch(/\d{4}-\d{2}-\d{2}|visit|uuid|position|lat|lon/i);
  });

  it("une liste vide est gardée : « j'ai tout supprimé » n'est pas « première visite »", () => {
    ecrire([]);
    expect(lire().trajets).toEqual([]);
  });

  it("« Effacer » fait tout disparaître", () => {
    ecrire([trajet()]);
    effacer();
    expect(window.localStorage.length).toBe(0);
    expect(lire().trajets).toBeNull();
  });

  it.each([
    ["du texte qui n'est pas du JSON", "pas du json"],
    ["un nombre", "42"],
    ["null", "null"],
    ["une autre version", JSON.stringify({ version: 99, trajets: [] })],
    ["des trajets qui ne sont pas une liste", JSON.stringify({ version: VERSION, trajets: "x" })],
    [
      "un trajet avec un champ en trop",
      JSON.stringify({ version: VERSION, trajets: [{ ...trajet(), email: "a@b.c" }] }),
    ],
    [
      "un trajet sans tronçon",
      JSON.stringify({ version: VERSION, trajets: [trajet({ troncons: [] })] }),
    ],
    [
      "un trajet de cinq tronçons",
      JSON.stringify({
        version: VERSION,
        trajets: [
          trajet({ troncons: ["ROAD_001", "ROAD_002", "ROAD_003", "ROAD_004", "ROAD_005"] }),
        ],
      }),
    ],
    [
      "un identifiant de tronçon étranger",
      JSON.stringify({ version: VERSION, trajets: [trajet({ troncons: ["../../x"] })] }),
    ],
    [
      "un nom trop long",
      JSON.stringify({ version: VERSION, trajets: [trajet({ nom: "x".repeat(41) })] }),
    ],
    [
      "trop de trajets",
      JSON.stringify({
        version: VERSION,
        trajets: Array.from({ length: 13 }, (_, i) => trajet({ id: `t-${i}` })),
      }),
    ],
  ])("ignore sans erreur %s", (_nom, brut) => {
    window.localStorage.setItem(CLE, brut);
    expect(lire()).toEqual({ trajets: null, disponible: true });
  });

  it("sans stockage (mode privé), l'application marche sans mémoire", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("refusé", "SecurityError");
    });
    expect(lire()).toEqual({ trajets: null, disponible: false });
    expect(ecrire([trajet()])).toBe(false);
    expect(() => effacer()).not.toThrow();
  });
});
