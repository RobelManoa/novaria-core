import { describe, expect, it } from "vitest";
import { STALE_AFTER_MS, ago, formatTime } from "../src/format";

describe("formatTime", () => {
  it("écrit l'heure en français sur 24 h", () => {
    expect(formatTime("2026-11-20T09:10:00Z")).toMatch(/^\d{2}:\d{2}$/);
  });
  it("dit « heure inconnue » d'une date illisible, jamais « Invalid Date »", () => {
    expect(formatTime("n'importe quoi")).toBe("heure inconnue");
  });
});

describe("ago", () => {
  const t = Date.parse("2026-11-20T09:00:00Z");
  it.each([
    [0, "à l'instant"],
    [59_000, "à l'instant"],
    [60_000, "il y a 1 min"],
    [3 * 60_000, "il y a 3 min"],
    [59 * 60_000, "il y a 59 min"],
    [60 * 60_000, "il y a 1 h"],
    [5 * 3_600_000, "il y a 5 h"],
    [24 * 3_600_000, "il y a 1 j"],
    [3 * 86_400_000, "il y a 3 j"],
  ])("%i ms d'écart : « %s »", (ecart, texte) => {
    expect(ago(t + ecart, t)).toBe(texte);
  });
  it("une horloge en avance ne donne jamais de durée négative", () => {
    expect(ago(t - 120_000, t)).toBe("à l'instant");
  });
  it("l'information est dite ancienne au-delà de 10 minutes", () => {
    expect(STALE_AFTER_MS).toBe(600_000);
  });
});
