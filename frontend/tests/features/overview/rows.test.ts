import { describe, expect, it } from "vitest";
import { intersectionRows, latestWindowEnd } from "@/features/overview/rows";
import type { Indicator } from "@/services/traitement";
import { SIGNAL, SIGNAL_2 } from "../../fixtures/signals";

function indicator(changes: Partial<Indicator>): Indicator {
  return {
    indicator_id: "i",
    intersection_id: "INT_01",
    road_segment_id: "ROAD_001",
    window_start: "2026-10-20T08:00:00Z",
    window_size_s: 60,
    average_speed_kmh: 30,
    vehicle_count: 10,
    flow_veh_per_min: 10,
    speed_ratio: 0.6,
    sample_count: 60,
    expected_sample_count: 60,
    congestion_state: "FREE_FLOW",
    classifier_version: "regles-v0",
    provenance: { source_type: "SIMULATED", run_id: "r", scenario_id: "demo", seed: 1 },
    ...changes,
  };
}

describe("intersectionRows", () => {
  it("regroupe les tronçons par carrefour et pondère la vitesse par les véhicules", () => {
    const rows = intersectionRows(
      [
        indicator({ road_segment_id: "ROAD_001", average_speed_kmh: 20, vehicle_count: 30 }),
        indicator({
          road_segment_id: "ROAD_002",
          average_speed_kmh: 40,
          vehicle_count: 10,
          congestion_state: "CONGESTED",
          flow_veh_per_min: 5,
        }),
        indicator({ intersection_id: "INT_02", road_segment_id: "ROAD_010" }),
      ],
      [SIGNAL],
    );
    expect(rows.map((row) => row.intersectionId)).toEqual(["INT_01", "INT_02"]);
    expect(rows[0].segmentCount).toBe(2);
    expect(rows[0].stateCounts.CONGESTED).toBe(1);
    expect(rows[0].speedKmh).toBe(25); // (20×30 + 40×10) / 40
    expect(rows[0].flowVehPerMin).toBe(15);
    expect(rows[0].signal).toBe(SIGNAL);
    expect(rows[1].signal).toBeNull();
  });

  it("garde un carrefour à feux sans indicateur, et ne l'invente pas de vitesse", () => {
    const rows = intersectionRows([], [SIGNAL_2]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ intersectionId: "INT_02", segmentCount: 0, speedKmh: null });
  });

  it("n'invente pas de vitesse quand aucun véhicule n'a été compté", () => {
    const [row] = intersectionRows([indicator({ average_speed_kmh: null, vehicle_count: 0 })], []);
    expect(row.speedKmh).toBeNull();
  });
});

describe("latestWindowEnd", () => {
  it("rend la fin de la fenêtre la plus récente, et null sans indicateur", () => {
    expect(latestWindowEnd([])).toBeNull();
    expect(
      latestWindowEnd([
        indicator({ window_start: "2026-10-20T08:00:00Z" }),
        indicator({ window_start: "2026-10-20T08:05:00Z", window_size_s: 300 }),
      ]),
    ).toBe(Date.parse("2026-10-20T08:10:00Z"));
  });
});
