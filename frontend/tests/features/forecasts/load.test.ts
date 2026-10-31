import { afterEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { HORIZONS, loadForecastView, loadSegments } from "@/features/forecasts/load";
import type { Forecast, Indicator } from "@/services/traitement";

const provenance = {
  source_type: "SIMULATED",
  run_id: "run-7",
  scenario_id: "demo",
  seed: 3,
} as const;

function forecast(
  segment: string,
  horizonMin: number,
  issuedAt = "2026-10-20T08:00:00Z",
): Forecast {
  const target = new Date(Date.parse(issuedAt) + horizonMin * 60_000);
  return {
    road_segment_id: segment,
    issued_at: issuedAt,
    horizon_min: horizonMin,
    target_time: target.toISOString().replace(".000Z", "Z"),
    predicted_speed_ratio: 0.6,
    model: { kind: "REFERENCE", name: "persistance", version: "v0", run_id: null },
    provenance,
  };
}

function indicator(segment: string, start: string): Indicator {
  return {
    indicator_id: `run-7:${segment}:300:${Date.parse(start)}`,
    road_segment_id: segment,
    intersection_id: "INT_01",
    window_start: start,
    window_size_s: 300,
    vehicle_count: 1,
    flow_veh_per_min: 1,
    average_speed_kmh: 30,
    speed_ratio: 0.6,
    sample_count: 6,
    expected_sample_count: 6,
    congestion_state: "SLOW",
    classifier_version: "regles-v0",
    provenance,
  };
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

const urls = (spy: MockInstance<typeof fetch>) =>
  spy.mock.calls.map(([request]) => new URL((request as Request).url));

describe("loadSegments", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lit les prévisions de tous les tronçons à 15 minutes et les trie par tronçon", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(json({ items: [forecast("ROAD_010", 15), forecast("ROAD_002", 15)] }));

    const items = await loadSegments();

    const [url] = urls(spy);
    expect(url.pathname).toBe("/api/v1/forecasts");
    expect(url.searchParams.get("horizon_min")).toBe("15");
    expect(url.searchParams.has("road_segment_id")).toBe(false);
    expect(items.map((item) => item.road_segment_id)).toEqual(["ROAD_002", "ROAD_010"]);
  });

  it("laisse passer l'erreur de l'API", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 503 }));
    await expect(loadSegments()).rejects.toMatchObject({ code: "UPSTREAM_UNAVAILABLE" });
  });
});

describe("loadForecastView", () => {
  afterEach(() => vi.restoreAllMocks());

  function serve(forecasts: (url: URL) => Forecast[], observed: Indicator[] = []) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL((input as Request).url);
      if (url.pathname === "/api/v1/forecasts") return json({ items: forecasts(url) });
      return json({ items: observed, next_cursor: null });
    });
  }

  it("demande une prévision du tronçon à chaque horizon", async () => {
    const spy = serve((url) => [forecast("ROAD_001", Number(url.searchParams.get("horizon_min")))]);

    const view = await loadForecastView("ROAD_001", 300);

    const calls = urls(spy).filter((url) => url.pathname === "/api/v1/forecasts");
    expect(calls.map((url) => Number(url.searchParams.get("horizon_min")))).toEqual([...HORIZONS]);
    for (const url of calls)
      expect(url.searchParams.getAll("road_segment_id")).toEqual(["ROAD_001"]);
    expect(view.forecasts.map((item) => item.horizon_min)).toEqual([...HORIZONS]);
  });

  it("lit l'observé du même tronçon et du même run, de 2 h avant l'émission à la fin du dernier horizon", async () => {
    const spy = serve(
      (url) => [forecast("ROAD_001", Number(url.searchParams.get("horizon_min")))],
      [indicator("ROAD_001", "2026-10-20T07:55:00Z")],
    );

    const view = await loadForecastView("ROAD_001", 300);

    const list = urls(spy).find((url) => url.pathname === "/api/v1/indicators") as URL;
    expect(list.searchParams.get("road_segment_id")).toBe("ROAD_001");
    expect(list.searchParams.get("run_id")).toBe("run-7");
    expect(list.searchParams.get("window_size_s")).toBe("300");
    // Émission 08:00 : départ à 06:00. Dernier horizon 60 min → 09:00, plus une fenêtre de 5 min (borne exclue).
    expect(list.searchParams.get("from")).toBe("2026-10-20T06:00:00Z");
    expect(list.searchParams.get("to")).toBe("2026-10-20T09:05:00Z");
    expect(view.observed).toHaveLength(1);
    expect(view.truncated).toBe(false);
  });

  it("ne lit pas l'observé quand l'API ne rend aucune prévision", async () => {
    const spy = serve(() => []);

    const view = await loadForecastView("ROAD_001", 300);

    expect(view).toEqual({ forecasts: [], observed: [], truncated: false });
    expect(urls(spy).some((url) => url.pathname === "/api/v1/indicators")).toBe(false);
  });

  it("ignore une prévision d'un autre tronçon que celui demandé", async () => {
    serve(() => [forecast("ROAD_001", 15), forecast("ROAD_099", 15)]);

    const view = await loadForecastView("ROAD_001", 300);

    expect(new Set(view.forecasts.map((item) => item.road_segment_id))).toEqual(
      new Set(["ROAD_001"]),
    );
  });

  it("échoue si une des prévisions échoue", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL((input as Request).url);
      return url.searchParams.get("horizon_min") === "30"
        ? new Response("{}", { status: 503 })
        : json({ items: [forecast("ROAD_001", Number(url.searchParams.get("horizon_min")))] });
    });

    await expect(loadForecastView("ROAD_001", 300)).rejects.toMatchObject({
      code: "UPSTREAM_UNAVAILABLE",
    });
  });
});
