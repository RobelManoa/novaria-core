import { describe, expect, it } from "vitest";
import { summarize } from "@/features/dashboard/summary";
import type { Indicator } from "@/services/traitement";

let counter = 0;

/** Un indicateur minimal valide ; seuls les champs lus par `summarize` comptent ici. */
function indicator(overrides: Partial<Indicator>): Indicator {
  counter += 1;
  return {
    indicator_id: `run:ROAD_001:60:${counter}`,
    road_segment_id: "ROAD_001",
    intersection_id: "INT_01",
    window_start: "2026-10-20T08:00:00Z",
    window_size_s: 60,
    vehicle_count: 0,
    flow_veh_per_min: 0,
    average_speed_kmh: null,
    speed_ratio: null,
    sample_count: 6,
    expected_sample_count: 6,
    congestion_state: "FREE_FLOW",
    classifier_version: "regles-v0",
    provenance: { source_type: "SIMULATED", run_id: "run", scenario_id: "demo", seed: 1 },
    ...overrides,
  };
}

describe("summarize", () => {
  it("rend un résumé vide sans indicateur", () => {
    expect(summarize([])).toEqual({
      indicatorCount: 0,
      vehicleCount: 0,
      averageSpeedKmh: null,
      averageFlowVehPerMin: null,
      segmentCount: 0,
      latest: [],
      stateCounts: { CONGESTED: 0, SLOW: 0, FREE_FLOW: 0, UNKNOWN: 0 },
      series: [],
    });
  });

  it("pondère la vitesse par le nombre de véhicules et additionne les véhicules", () => {
    // (10 × 60 + 30 × 20) / (10 + 30) = 30 km/h ; une moyenne simple donnerait 40.
    const summary = summarize([
      indicator({ vehicle_count: 10, average_speed_kmh: 60 }),
      indicator({ vehicle_count: 30, average_speed_kmh: 20, road_segment_id: "ROAD_002" }),
    ]);
    expect(summary.averageSpeedKmh).toBe(30);
    expect(summary.vehicleCount).toBe(40);
    expect(summary.indicatorCount).toBe(2);
  });

  it("ignore les fenêtres sans vitesse dans la moyenne, sans les retirer des totaux", () => {
    const summary = summarize([
      indicator({ vehicle_count: 10, average_speed_kmh: 50 }),
      indicator({
        vehicle_count: 0,
        average_speed_kmh: null,
        window_start: "2026-10-20T08:01:00Z",
      }),
    ]);
    expect(summary.averageSpeedKmh).toBe(50);
    expect(summary.indicatorCount).toBe(2);
  });

  it("n'invente pas de vitesse quand aucune fenêtre n'en a", () => {
    expect(summarize([indicator({ vehicle_count: 0 })]).averageSpeedKmh).toBeNull();
  });

  it("construit la série par fenêtre, en ordre chronologique, avec le débit cumulé des tronçons", () => {
    const summary = summarize([
      // Fournis du plus récent au plus ancien, comme l'API.
      indicator({
        window_start: "2026-10-20T08:01:00Z",
        vehicle_count: 4,
        average_speed_kmh: 40,
        flow_veh_per_min: 4,
      }),
      indicator({
        window_start: "2026-10-20T08:00:00Z",
        vehicle_count: 2,
        average_speed_kmh: 30,
        flow_veh_per_min: 2,
      }),
      indicator({
        window_start: "2026-10-20T08:00:00Z",
        road_segment_id: "ROAD_002",
        vehicle_count: 6,
        average_speed_kmh: 50,
        flow_veh_per_min: 6,
      }),
    ]);
    expect(summary.series).toEqual([
      { time: Date.parse("2026-10-20T08:00:00Z"), speedKmh: 45, flowVehPerMin: 8, vehicleCount: 8 },
      { time: Date.parse("2026-10-20T08:01:00Z"), speedKmh: 40, flowVehPerMin: 4, vehicleCount: 4 },
    ]);
    // Débit moyen = (8 + 4) / 2 fenêtres.
    expect(summary.averageFlowVehPerMin).toBe(6);
  });

  it("compte, par état, la dernière fenêtre de chaque tronçon", () => {
    const summary = summarize([
      indicator({ window_start: "2026-10-20T08:00:00Z", congestion_state: "FREE_FLOW" }),
      indicator({ window_start: "2026-10-20T08:02:00Z", congestion_state: "CONGESTED" }),
      indicator({ window_start: "2026-10-20T08:01:00Z", congestion_state: "SLOW" }),
      indicator({ road_segment_id: "ROAD_002", congestion_state: "FREE_FLOW" }),
      indicator({ road_segment_id: "ROAD_003", congestion_state: "UNKNOWN" }),
    ]);
    expect(summary.segmentCount).toBe(3);
    expect(summary.latest.map((item) => [item.road_segment_id, item.window_start])).toEqual([
      ["ROAD_001", "2026-10-20T08:02:00Z"],
      ["ROAD_002", "2026-10-20T08:00:00Z"],
      ["ROAD_003", "2026-10-20T08:00:00Z"],
    ]);
    expect(summary.stateCounts).toEqual({ CONGESTED: 1, SLOW: 0, FREE_FLOW: 1, UNKNOWN: 1 });
  });
});
