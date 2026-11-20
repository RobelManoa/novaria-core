import { describe, expect, it } from "vitest";
import { countByState, groupByIntersection, latestUpdate } from "../src/summary";
import { network, segment } from "./fixtures";

describe("résumé", () => {
  it("compte chaque état, y compris ceux à zéro", () => {
    expect(countByState(network())).toEqual({ CONGESTED: 1, SLOW: 1, FREE_FLOW: 3, UNKNOWN: 1 });
    expect(countByState([])).toEqual({ CONGESTED: 0, SLOW: 0, FREE_FLOW: 0, UNKNOWN: 0 });
  });

  it("groupe par carrefour dans l'ordre des numéros, tronçons du nord à l'ouest", () => {
    const melange = [
      segment({ road_segment_id: "ROAD_010", intersection_id: "INT_10", approach: "W" }),
      segment({ road_segment_id: "ROAD_002", intersection_id: "INT_02", approach: "W" }),
      segment({ road_segment_id: "ROAD_001", intersection_id: "INT_02", approach: "S" }),
      segment({ road_segment_id: "ROAD_003", intersection_id: "INT_02", approach: "N" }),
    ];
    const groupes = groupByIntersection(melange);
    expect(groupes.map((g) => g.intersection)).toEqual(["INT_02", "INT_10"]);
    expect(groupes[0].segments.map((s) => s.approach)).toEqual(["N", "S", "W"]);
  });

  it("ne modifie pas la liste reçue", () => {
    const original = network();
    const copie = structuredClone(original);
    groupByIntersection(original);
    expect(original).toEqual(copie);
  });

  it("la mise à jour est la plus récente des tronçons ; rien si la liste est vide", () => {
    const liste = [
      segment({ updated_at: "2026-11-20T09:05:00Z" }),
      segment({ updated_at: "2026-11-20T09:10:00Z" }),
    ];
    expect(latestUpdate(liste)).toBe("2026-11-20T09:10:00Z");
    expect(latestUpdate([])).toBeNull();
  });
});
