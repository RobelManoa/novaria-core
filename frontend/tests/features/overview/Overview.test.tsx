import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Overview from "@/features/overview/Overview";
import { setAccessToken } from "@/services/session";
import { ALERT, controlledStream } from "../../fixtures/alerts";
import { SIGNAL, SIGNAL_2, json, problem, withRole } from "../../fixtures/signals";

const INDICATOR = {
  indicator_id: "ind-1",
  intersection_id: "INT_01",
  road_segment_id: "ROAD_001",
  window_start: "2026-10-20T08:00:00Z",
  window_size_s: 60,
  average_speed_kmh: 22.5,
  vehicle_count: 40,
  flow_veh_per_min: 40,
  speed_ratio: 0.45,
  sample_count: 60,
  expected_sample_count: 60,
  congestion_state: "CONGESTED",
  classifier_version: "regles-v0",
  provenance: { source_type: "SIMULATED", run_id: "r", scenario_id: "demo", seed: 1 },
};

/** Les quatre sources de la vue : indicateurs, alertes (liste + flux) et feux. */
function serve(overrides: Record<string, () => Response> = {}) {
  const stream = controlledStream();
  const routes: Record<string, () => Response> = {
    "GET /api/v1/indicators/latest": () => json({ items: [INDICATOR] }),
    "GET /api/v1/alerts": () => json({ items: [ALERT], next_cursor: null }),
    "GET /api/v1/signals": () => json({ items: [SIGNAL, SIGNAL_2] }),
    "GET /api/v1/events/stream": () => stream.response,
    ...overrides,
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const key = `${request.method} ${new URL(request.url).pathname}`;
    const route = routes[key];
    if (!route) throw new Error(`Appel non prévu : ${key}`);
    return route();
  });
  return stream;
}

const card = (label: string) => screen.getByText(label).closest("div") as HTMLElement;

describe("Overview : la vue d'ensemble en direct", () => {
  beforeEach(() => setAccessToken("jeton-d-essai"));
  afterEach(() => {
    vi.restoreAllMocks();
    setAccessToken(null);
  });

  it("affiche un chiffre lu auprès de chacun des quatre services", async () => {
    serve();
    render(withRole("viewer", <Overview />));

    expect(await within(card("Traitement")).findByText("1 sur 1")).toBeInTheDocument();
    expect(within(card("Collecte")).getByText("08:01")).toBeInTheDocument(); // fin de la fenêtre
    expect(await within(card("Alertes")).findByText("1")).toBeInTheDocument();
    expect(await within(card("Réponse")).findByText("0 sur 2")).toBeInTheDocument();
  });

  it("réunit indicateurs et feux dans le tableau par carrefour", async () => {
    serve();
    render(withRole("viewer", <Overview />));

    const table = await screen.findByRole("table");
    const row = (id: string) => within(table).getByText(id).closest("tr") as HTMLElement;
    await within(row("INT_01")).findByText("Automatique · phase P1");
    const text = (id: string) => (row(id).textContent ?? "").replace(/\s+/g, " ").trim();
    expect(text("INT_01")).toBe("INT_011 sur 122,5 km/h40,0 véh/minAutomatique · phase P1");
    expect(text("INT_02")).toBe("INT_02———Plan fixe (mode dégradé) · phase P2");
  });

  it("dit « Indisponible » pour le service en panne sans masquer les autres", async () => {
    serve({ "GET /api/v1/signals": () => problem(503, "UPSTREAM_UNAVAILABLE") });
    render(withRole("viewer", <Overview />));

    expect(await within(card("Réponse")).findByText("Indisponible")).toBeInTheDocument();
    expect(await within(card("Traitement")).findByText("1 sur 1")).toBeInTheDocument();
  });
});
