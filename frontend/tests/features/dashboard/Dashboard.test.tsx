import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "@/features/dashboard/Dashboard";
import { MAX_PAGES } from "@/features/dashboard/load";
import type { Indicator } from "@/services/traitement";

function indicator(overrides: Partial<Indicator> = {}): Indicator {
  return {
    indicator_id: "run-1:ROAD_001:300:1",
    road_segment_id: "ROAD_001",
    intersection_id: "INT_01",
    window_start: "2026-10-20T08:00:00Z",
    window_size_s: 300,
    vehicle_count: 10,
    flow_veh_per_min: 2,
    average_speed_kmh: 40,
    speed_ratio: 0.8,
    sample_count: 6,
    expected_sample_count: 6,
    congestion_state: "FREE_FLOW",
    classifier_version: "regles-v0",
    provenance: { source_type: "SIMULATED", run_id: "run-1", scenario_id: "demo", seed: 1 },
    ...overrides,
  };
}

const page = (items: Indicator[], next: string | null = null) =>
  new Response(JSON.stringify({ items, next_cursor: next }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

const problem = (status: number, code: string, correlationId?: string) =>
  new Response(
    JSON.stringify({
      type: "about:blank",
      title: "Erreur",
      status,
      code,
      correlation_id: correlationId,
    }),
    { status, headers: { "content-type": "application/problem+json" } },
  );

const queryOf = (request: Request) => Object.fromEntries(new URL(request.url).searchParams);

describe("Dashboard : états de chargement, vide et erreur", () => {
  afterEach(() => vi.restoreAllMocks());

  it("annonce le chargement tant que l'API n'a pas répondu", () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    render(<Dashboard />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Chargement des indicateurs…");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("region", { name: "Indicateurs clés" })).not.toBeInTheDocument();
  });

  it("affiche l'erreur de l'API, sa référence, et relit l'API au clic sur « Réessayer »", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(problem(503, "UPSTREAM_UNAVAILABLE", "corr-42"))
      .mockImplementation(async () => page([indicator()]));
    render(<Dashboard />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Impossible de charger les indicateurs");
    expect(alert).toHaveTextContent("Un service est momentanément indisponible");
    expect(alert).toHaveTextContent("Référence à citer : corr-42.");

    await userEvent.click(within(alert).getByRole("button", { name: "Réessayer" }));

    expect(await screen.findByRole("region", { name: "Indicateurs clés" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(spy.mock.calls.length).toBeGreaterThan(1);
  });

  it("dit que le serveur est injoignable quand le réseau est coupé", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(<Dashboard />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Le serveur est injoignable");
  });

  it("propose les fenêtres de 5 minutes quand celles d'une minute sont vides", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      queryOf(input as Request).window_size_s === "300" ? page([indicator()]) : page([]),
    );
    render(<Dashboard />);

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Aucun indicateur pour ces filtres",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Essayer les fenêtres de 5 minutes" }),
    );

    expect(await screen.findByRole("region", { name: "Indicateurs clés" })).toBeInTheDocument();
    expect(screen.getByLabelText("Taille des fenêtres")).toHaveValue("300");
  });

  it("n'a plus de bouton à proposer quand les fenêtres de 5 minutes sont déjà choisies", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => page([]));
    render(<Dashboard />);
    await screen.findByText("Aucun indicateur pour ces filtres");

    await userEvent.selectOptions(screen.getByLabelText("Taille des fenêtres"), "300");

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /fenêtres de 5 minutes/ }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Aucun indicateur pour ces filtres");
  });

  it("invite à regarder tout le réseau quand la zone choisie est vide", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      queryOf(input as Request).intersection_id
        ? page([])
        : page([
            indicator({ intersection_id: "INT_01" }),
            indicator({ intersection_id: "INT_02", road_segment_id: "ROAD_005" }),
          ]),
    );
    render(<Dashboard />);
    await screen.findByRole("region", { name: "Indicateurs clés" });

    await userEvent.selectOptions(screen.getByLabelText("Zone"), "INT_02");

    expect(await screen.findByRole("status")).toHaveTextContent("Essayez « Tout le réseau »");
    // La liste des zones reste disponible pour en changer.
    expect(
      within(screen.getByLabelText("Zone"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Tout le réseau", "Carrefour INT_01", "Carrefour INT_02"]);
  });

  it("prévient quand la lecture est tronquée par la limite de pages", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      queryOf(input as Request).limit === "1" ? page([indicator()]) : page([indicator()], "suite"),
    );
    render(<Dashboard />);

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("La lecture s'arrête à 5 000 indicateurs");
    expect(MAX_PAGES * 500).toBe(5000);
  });

  it("ne montre pas d'avertissement quand toutes les pages sont lues", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => page([indicator()]));
    render(<Dashboard />);

    await screen.findByRole("region", { name: "Indicateurs clés" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("dit toujours l'origine des données, jusqu'au jeu pour une donnée réelle historique", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      page([
        indicator({
          provenance: {
            source_type: "REAL_HISTORICAL",
            run_id: "paris-2026-10-17",
            dataset_id: "paris-comptages-routiers",
          },
        }),
      ]),
    );
    render(<Dashboard />);

    const meta = await screen.findByText(/Données réelles \(historique\)/);
    expect(meta).toHaveTextContent("exécution paris-2026-10-17");
    expect(meta).toHaveTextContent("jeu paris-comptages-routiers");
    expect(screen.queryByText(/Données simulées/)).not.toBeInTheDocument();
  });

  it("affiche un tiret, pas un zéro, quand aucune fenêtre n'a de vitesse", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      page([
        indicator({
          vehicle_count: 0,
          average_speed_kmh: null,
          speed_ratio: null,
          flow_veh_per_min: 0,
        }),
      ]),
    );
    render(<Dashboard />);

    const region = await screen.findByRole("region", { name: "Indicateurs clés" });
    const label = within(region).getByText("Vitesse moyenne");
    expect(label.nextElementSibling).toHaveTextContent(/^—\s*km\/h$/);
  });

  it("ignore la réponse tardive d'un ancien filtre", async () => {
    let releaseOldRequest: (response: Response) => void = () => {};
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (queryOf(input as Request).window_size_s === "60") {
        return new Promise<Response>((resolve) => {
          releaseOldRequest = resolve;
        });
      }
      return Promise.resolve(page([indicator({ vehicle_count: 77 })]));
    });
    render(<Dashboard />);

    // Les fenêtres d'une minute n'ont pas répondu ; l'utilisateur passe aux fenêtres de 5 minutes.
    await userEvent.selectOptions(screen.getByLabelText("Taille des fenêtres"), "300");
    const region = await screen.findByRole("region", { name: "Indicateurs clés" });
    expect(within(region).getByText("Véhicules comptés").nextElementSibling).toHaveTextContent(
      "77",
    );

    // La réponse de l'ancien filtre arrive après : elle ne doit rien changer.
    releaseOldRequest(page([]));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText("Aucun indicateur pour ces filtres")).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Indicateurs clés" })).getByText(
        "Véhicules comptés",
      ).nextElementSibling,
    ).toHaveTextContent("77");
  });

  it("relit l'API avec la période et la zone choisies", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => page([indicator()]));
    render(<Dashboard />);
    await screen.findByRole("region", { name: "Indicateurs clés" });
    spy.mockClear();

    await userEvent.selectOptions(screen.getByLabelText("Période"), "24");

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    const [newest, list] = spy.mock.calls.map(([request]) => queryOf(request as Request));
    expect(newest).toMatchObject({ window_size_s: "60", limit: "1" });
    // Fin de la dernière fenêtre (08:00 + 5 min = 08:05, mais l'indicateur de test dure 300 s) moins 24 h.
    expect(list).toMatchObject({
      window_size_s: "60",
      run_id: "run-1",
      from: "2026-10-19T08:05:00Z",
      to: "2026-10-20T08:05:00Z",
    });
  });
});
