import { describe, expect, it } from "vitest";
import { compareForecasts } from "@/features/forecasts/compare";
import type { Forecast, Indicator } from "@/services/traitement";

const provenance = {
  source_type: "SIMULATED",
  run_id: "run-1",
  scenario_id: "demo",
  seed: 1,
} as const;

function forecast(horizonMin: number, ratio: number, overrides: Partial<Forecast> = {}): Forecast {
  const issued = Date.parse("2026-10-20T08:00:00Z");
  return {
    road_segment_id: "ROAD_001",
    issued_at: "2026-10-20T08:00:00Z",
    horizon_min: horizonMin,
    target_time: new Date(issued + horizonMin * 60_000).toISOString().replace(".000Z", "Z"),
    predicted_speed_ratio: ratio,
    model: { kind: "REFERENCE", name: "persistance", version: "v0", run_id: null },
    provenance,
    ...overrides,
  };
}

function observed(start: string, ratio: number | null, sizeS = 300): Indicator {
  return {
    indicator_id: `run-1:ROAD_001:${sizeS}:${Date.parse(start)}`,
    road_segment_id: "ROAD_001",
    intersection_id: "INT_01",
    window_start: start,
    window_size_s: sizeS as 60 | 300,
    vehicle_count: 5,
    flow_veh_per_min: 1,
    average_speed_kmh: ratio === null ? null : ratio * 50,
    speed_ratio: ratio,
    sample_count: 6,
    expected_sample_count: 6,
    congestion_state: "FREE_FLOW",
    classifier_version: "regles-v0",
    provenance,
  };
}

describe("compareForecasts", () => {
  it("trie les lignes par horizon, quel que soit l'ordre reçu", () => {
    const rows = compareForecasts([forecast(30, 0.5), forecast(5, 0.7), forecast(15, 0.6)], []);
    expect(rows.map((row) => row.horizonMin)).toEqual([5, 15, 30]);
  });

  it("garde l'observé vide tant que l'instant prévu n'a pas été observé", () => {
    const [row] = compareForecasts([forecast(15, 0.62)], [observed("2026-10-20T07:55:00Z", 0.6)]);
    expect(row.observedRatio).toBeNull();
    expect(row.difference).toBeNull();
    expect(row.predictedRatio).toBe(0.62);
  });

  it("prend la fenêtre qui contient l'instant prévu et rend l'écart prévu − observé", () => {
    // Instant prévu : 08:15. Fenêtre de 5 minutes 08:15 → 08:20 : elle le contient (début inclus).
    const [row] = compareForecasts(
      [forecast(15, 0.62)],
      [observed("2026-10-20T08:10:00Z", 0.5), observed("2026-10-20T08:15:00Z", 0.6)],
    );
    expect(row.observedRatio).toBe(0.6);
    expect(row.difference).toBe(0.02);
  });

  it("trouve l'instant prévu à l'intérieur d'une fenêtre, pas seulement à son début", () => {
    // 08:17 est dans [08:15, 08:20[.
    const [row] = compareForecasts([forecast(17, 0.5)], [observed("2026-10-20T08:15:00Z", 0.55)]);
    expect(row.observedRatio).toBe(0.55);
    expect(row.difference).toBe(-0.05);
  });

  it("exclut la fin de la fenêtre (borne exclue)", () => {
    const [row] = compareForecasts([forecast(20, 0.5)], [observed("2026-10-20T08:15:00Z", 0.55)]);
    expect(row.observedRatio).toBeNull();
  });

  it("ne compare pas à une fenêtre sans vitesse", () => {
    const [row] = compareForecasts([forecast(15, 0.5)], [observed("2026-10-20T08:15:00Z", null)]);
    expect(row.observedRatio).toBeNull();
    expect(row.difference).toBeNull();
  });

  it("ne rend jamais « -0 » pour un écart nul", () => {
    const [row] = compareForecasts([forecast(15, 0.6)], [observed("2026-10-20T08:15:00Z", 0.6)]);
    expect(Object.is(row.difference, 0)).toBe(true);
  });

  it("reprend l'état prévu du contrat, absent ou non", () => {
    const rows = compareForecasts(
      [forecast(5, 0.7, { predicted_state: "FREE_FLOW" }), forecast(15, 0.3)],
      [],
    );
    expect(rows.map((row) => row.predictedState)).toEqual(["FREE_FLOW", undefined]);
  });

  it("rend une liste vide sans prévision", () => {
    expect(compareForecasts([], [observed("2026-10-20T08:15:00Z", 0.5)])).toEqual([]);
  });
});
