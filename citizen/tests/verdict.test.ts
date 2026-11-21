import { describe, expect, it } from "vitest";
import {
  VERDICT_ETAT,
  VERDICT_PHRASE,
  VERDICT_TITRE,
  verdictDuTrajet,
  type Verdict,
} from "../src/verdict";
import type { CongestionState } from "../src/types";
import { segment } from "./fixtures";

const lire = (...etats: (CongestionState | null)[]) => {
  const parId = new Map();
  const troncons = etats.map((etat, i) => {
    const id = `ROAD_${String(i + 1).padStart(3, "0")}`;
    if (etat !== null) parId.set(id, segment({ road_segment_id: id, state: etat }));
    return id;
  });
  return verdictDuTrajet({ troncons }, parId);
};

describe("la décision de départ d'un trajet : une règle sur le pire état", () => {
  it.each<[string, (CongestionState | null)[], Verdict]>([
    ["tout fluide", ["FREE_FLOW", "FREE_FLOW"], "LIBRE"],
    ["un seul tronçon fluide", ["FREE_FLOW"], "LIBRE"],
    ["un tronçon ralenti", ["FREE_FLOW", "SLOW"], "RALENTI"],
    ["un tronçon congestionné", ["FREE_FLOW", "CONGESTED"], "BLOQUE"],
    ["le pire l'emporte : ralenti et congestionné", ["SLOW", "CONGESTED"], "BLOQUE"],
    ["congestionné malgré un tronçon sans mesure", ["UNKNOWN", "CONGESTED"], "BLOQUE"],
    ["ralenti malgré un tronçon sans mesure", [null, "SLOW"], "RALENTI"],
    [
      "fluide là où l'on mesure, un tronçon sans mesure : prudence",
      ["FREE_FLOW", "UNKNOWN"],
      "INCOMPLET",
    ],
    ["fluide et un tronçon absent de la réponse : prudence", ["FREE_FLOW", null], "INCOMPLET"],
    ["aucune mesure", ["UNKNOWN", "UNKNOWN"], "INDISPONIBLE"],
    ["tronçons absents de la réponse", [null, null], "INDISPONIBLE"],
  ])("%s", (_nom, etats, attendu) => {
    expect(lire(...etats).verdict).toBe(attendu);
  });

  it("un trajet sans tronçon n'est jamais « Libre »", () => {
    expect(verdictDuTrajet({ troncons: [] }, new Map()).verdict).not.toBe("LIBRE");
  });

  it("dit où ça pose problème : les tronçons qui donnent le verdict, par leur nom", () => {
    const l = lire("FREE_FLOW", "CONGESTED", "CONGESTED");
    expect(l.critiques.map((t) => t.id)).toEqual(["ROAD_002", "ROAD_003"]);
    expect(l.critiques[0].nom).toBe("Place de la Gare, en venant de l'est");
    expect(lire("FREE_FLOW").critiques).toEqual([]);
  });

  it("donne la mesure la plus récente, ou aucune", () => {
    const parId = new Map([
      ["ROAD_001", segment({ road_segment_id: "ROAD_001", updated_at: "2026-11-20T09:10:00Z" })],
      ["ROAD_002", segment({ road_segment_id: "ROAD_002", updated_at: "2026-11-20T09:11:00Z" })],
    ]);
    expect(verdictDuTrajet({ troncons: ["ROAD_001", "ROAD_002"] }, parId).miseAJour).toBe(
      "2026-11-20T09:11:00Z",
    );
    expect(verdictDuTrajet({ troncons: ["ROAD_001"] }, new Map()).miseAJour).toBeNull();
  });

  it("chaque verdict a un titre, une phrase et un état de couleur, sans code technique", () => {
    for (const v of Object.keys(VERDICT_TITRE) as Verdict[]) {
      expect(VERDICT_TITRE[v].length).toBeGreaterThan(2);
      expect(VERDICT_PHRASE[v].length).toBeGreaterThan(10);
      expect(VERDICT_ETAT[v]).toBeDefined();
      expect(`${VERDICT_TITRE[v]} ${VERDICT_PHRASE[v]}`).not.toMatch(/[A-Z]{3,}_|ROAD|INT_/);
    }
  });

  it("n'annonce jamais une durée ni une heure : la phrase décrit, elle ne promet rien", () => {
    for (const phrase of Object.values(VERDICT_PHRASE))
      expect(phrase).not.toMatch(/\d+\s?(min|h)\b|\d{1,2}\s?h\s?\d{0,2}/);
  });
});
