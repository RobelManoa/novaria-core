import { afterEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { DEFAULT_FILTERS } from "@/features/dashboard/filters";
import { loadDashboard } from "@/features/dashboard/load";

function row(segment: string, start: string, run = "run-1") {
  return {
    indicator_id: `${run}:${segment}:60:${Date.parse(start)}`,
    road_segment_id: segment,
    intersection_id: "INT_01",
    window_start: start,
    window_size_s: 60,
    vehicle_count: 1,
    flow_veh_per_min: 1,
    average_speed_kmh: 30,
    speed_ratio: 0.5,
    sample_count: 6,
    expected_sample_count: 6,
    congestion_state: "SLOW",
    classifier_version: "regles-v0",
    provenance: { source_type: "SIMULATED", run_id: run, scenario_id: "demo", seed: 1 },
  };
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function requestedUrls(spy: MockInstance<typeof fetch>): URL[] {
  return spy.mock.calls.map(([request]) => new URL((request as Request).url));
}

describe("loadDashboard", () => {
  afterEach(() => vi.restoreAllMocks());

  it("cale la période sur la dernière fenêtre de données, dans le run le plus récent", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        json({ items: [row("ROAD_001", "2026-10-30T08:55:00Z", "run-9")], next_cursor: null }),
      )
      .mockResolvedValueOnce(
        json({ items: [row("ROAD_001", "2026-10-30T08:55:00Z", "run-9")], next_cursor: null }),
      );

    const data = await loadDashboard({ ...DEFAULT_FILTERS, periodHours: 6, windowSizeS: 60 });

    const [newest, list] = requestedUrls(spy);
    expect(newest.searchParams.get("limit")).toBe("1");
    expect(newest.searchParams.get("window_size_s")).toBe("60");
    // La fenêtre de 08:55 dure une minute : la période se termine à 08:56 (borne exclue) et remonte de 6 h.
    expect(list.searchParams.get("to")).toBe("2026-10-30T08:56:00Z");
    expect(list.searchParams.get("from")).toBe("2026-10-30T02:56:00Z");
    expect(list.searchParams.get("run_id")).toBe("run-9");
    expect(list.searchParams.get("window_size_s")).toBe("60");
    expect(list.searchParams.get("limit")).toBe("500");
    expect(data.indicators).toHaveLength(1);
    expect(data.provenance?.run_id).toBe("run-9");
    expect(data.truncated).toBe(false);
  });

  it("transmet la zone aux deux appels", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        json({ items: [row("ROAD_001", "2026-10-30T08:55:00Z")], next_cursor: null }),
      )
      .mockResolvedValueOnce(json({ items: [], next_cursor: null }));

    await loadDashboard({ ...DEFAULT_FILTERS, intersectionId: "INT_03" });

    for (const url of requestedUrls(spy)) {
      expect(url.searchParams.get("intersection_id")).toBe("INT_03");
    }
  });

  it("n'appelle pas la liste quand il n'y a aucune donnée", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ items: [], next_cursor: null }));

    const data = await loadDashboard(DEFAULT_FILTERS);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(data).toEqual({ indicators: [], truncated: false, provenance: null });
  });

  it("signale une lecture tronquée", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL((input as Request).url);
      const items = [row("ROAD_001", "2026-10-30T08:55:00Z")];
      return json({ items, next_cursor: url.searchParams.get("limit") === "1" ? null : "suite" });
    });

    const data = await loadDashboard(DEFAULT_FILTERS);

    expect(data.truncated).toBe(true);
  });

  it("laisse passer l'erreur de l'API", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("{}", { status: 503 }));

    await expect(loadDashboard(DEFAULT_FILTERS)).rejects.toMatchObject({
      code: "UPSTREAM_UNAVAILABLE",
    });
  });
});
