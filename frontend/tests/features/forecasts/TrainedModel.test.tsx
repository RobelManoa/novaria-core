import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import TrainedModel from "@/features/forecasts/TrainedModel";
import type { ModelCard, SpeedForecastList, SpeedNetwork } from "@/services/traitement";

const CARD: ModelCard = {
  kind: "MODEL",
  name: "reseau-spatio-temporel",
  version: "1",
  run_id: null,
  trained_at: "2026-11-22T14:00:00Z",
  dataset: "METR-LA",
  source_type: "REAL_HISTORICAL",
  parameters: 38854,
  horizons_min: [5, 10, 15, 20, 25, 30],
  periods: {
    apprentissage: { start: "2012-03-01T00:55:00Z", end: "2012-05-23T06:35:00Z", steps: 23973 },
    test: { start: "2012-06-10T03:35:00Z", end: "2012-06-27T23:55:00Z", steps: 5141 },
  },
  test: {
    "15": {
      mae_model_mph: 2.8,
      mae_persistence_mph: 3.456,
      gain: 0.19,
      interval_95: [-0.62, -0.5],
      mae_hgb_mph: 2.876,
    },
    "30": {
      mae_model_mph: 3.2,
      mae_persistence_mph: 4.145,
      gain: 0.228,
      interval_95: [-1.0, -0.8],
      mae_hgb_mph: 3.337,
    },
  },
  variables: ["vitesse des 12 derniers pas", "les 10 capteurs voisins"],
  limits: ["appris sur METR-LA seulement : ne sert que ce réseau"],
  file_sha256: "a".repeat(64),
};

const NETWORK: SpeedNetwork = {
  network_id: "metr-la",
  label: "METR-LA (Los Angeles, 2012)",
  description: "Vitesses réelles historiques",
  source_type: "REAL_HISTORICAL",
  step_s: 300,
  speed_unit: "mph",
  coverage: {
    first: "2012-05-23T00:00:00Z",
    last: "2012-06-27T23:55:00Z",
    steps: 10000,
    sensors: 207,
  },
  model: CARD,
  model_problem: null,
};

const FORECASTS: SpeedForecastList = {
  network_id: "metr-la",
  as_of: "2012-06-27T23:55:00Z",
  horizon_min: 15,
  model: CARD,
  sensors_without_model: 0,
  items: [
    {
      sensor_id: "773869",
      target_time: "2012-06-28T00:10:00Z",
      predicted_speed_kmh: 90,
      persistence_speed_kmh: 100,
      observed_speed_kmh: 92,
    },
    {
      sensor_id: "767541",
      target_time: "2012-06-28T00:10:00Z",
      predicted_speed_kmh: 50,
      persistence_speed_kmh: 51,
      observed_speed_kmh: 54,
    },
    {
      sensor_id: "716328",
      target_time: "2012-06-28T00:10:00Z",
      predicted_speed_kmh: 70,
      persistence_speed_kmh: 70,
      observed_speed_kmh: null,
    },
  ],
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function serve(
  networks: SpeedNetwork[],
  forecasts: (url: URL) => Response = () => json(FORECASTS),
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL((input as Request).url);
    if (url.pathname === "/api/v1/speed-networks") return json({ items: networks });
    if (url.pathname === "/api/v1/speed-networks/metr-la/forecasts") return forecasts(url);
    throw new Error(`Appel non prévu : ${url.pathname}`);
  });
}

afterEach(() => vi.restoreAllMocks());

describe("le modèle entraîné", () => {
  it("ne montre rien quand aucun réseau de vitesse n'est chargé", async () => {
    serve([]);
    const { container } = render(<TrainedModel />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("dit pourquoi il n'y a pas de modèle, au lieu de se taire ou de montrer une persistance", async () => {
    serve([
      {
        ...NETWORK,
        model: null,
        model_problem: "Aucun modèle entraîné pour le réseau « metr-la ».",
      },
    ]);
    render(<TrainedModel />);
    expect(await screen.findByText("Pas de modèle entraîné utilisable")).toBeVisible();
    expect(screen.getByText(/Aucun modèle entraîné/)).toBeVisible();
    expect(screen.queryByRole("region", { name: /Modèle entraîné :/ })).not.toBeInTheDocument();
  });

  it("explique le modèle : source, variables, erreur de test contre la persistance, limites", async () => {
    serve([NETWORK]);
    render(<TrainedModel />);
    const fiche = await screen.findByRole("region", {
      name: /Modèle entraîné : reseau-spatio-temporel/,
    });
    expect(fiche).toHaveTextContent("Données réelles (historique)");
    expect(fiche).toHaveTextContent("38 854 poids");
    expect(within(fiche).getByText("les 10 capteurs voisins")).toBeVisible();
    expect(within(fiche).getByText(/ne sert que ce réseau/)).toBeVisible();
    const lignes = within(fiche).getAllByRole("row").slice(1);
    expect(lignes.map((r) => r.textContent)).toEqual([
      expect.stringContaining("15 min"),
      expect.stringContaining("30 min"),
    ]);
    expect(lignes[0]).toHaveTextContent("19,0 %");
    expect(lignes[0]).toHaveTextContent("de -0,62 à -0,50 mph");
  });

  it("compare en direct le modèle à la persistance et à l'observé", async () => {
    serve([NETWORK]);
    render(<TrainedModel />);
    const direct = await screen.findByRole("region", { name: "Le modèle face au réel" });
    const bilan = await within(direct).findByText(/Sur 2 capteurs/);
    expect(bilan).toHaveTextContent("Sur 2 capteurs");
    expect(bilan).toHaveTextContent("erreur moyenne du modèle 3,00 km/h");
    expect(bilan).toHaveTextContent("de la persistance 5,50 km/h");
    expect(bilan).toHaveTextContent("plus proche du réel pour 50,0 % des capteurs");
    const lignes = within(direct).getAllByRole("row").slice(1);
    expect(lignes[0]).toHaveTextContent("773869"); // là où la persistance se trompe le plus
    expect(lignes[2]).toHaveTextContent("716328"); // sans observé : à la fin, erreurs absentes
    expect(lignes[2]).toHaveTextContent("—");
  });

  it("demande l'horizon choisi et la date choisie", async () => {
    const appels: URL[] = [];
    serve([NETWORK], (url) => {
      appels.push(url);
      return json(FORECASTS);
    });
    render(<TrainedModel />);
    await screen.findByText(/Sur 2 capteurs/);
    expect(appels[0]?.searchParams.get("as_of")).toBe("2012-06-27T22:55:00Z"); // une heure avant la fin : l'avenir est connu
    expect(appels[0]?.searchParams.get("horizon_min")).toBe("15");
    await userEvent.selectOptions(screen.getByLabelText("Horizon"), "30");
    await waitFor(() => expect(appels.at(-1)?.searchParams.get("horizon_min")).toBe("30"));
  });

  it("ne score rien quand les mesures de l'instant prévu manquent", async () => {
    const sansObserve = {
      ...FORECASTS,
      items: FORECASTS.items.map((i) => ({ ...i, observed_speed_kmh: null })),
    };
    serve([NETWORK], () => json(sansObserve));
    render(<TrainedModel />);
    expect(await screen.findByText(/rien à comparer/)).toBeVisible();
  });

  it("dit une erreur 404 comme une absence de mesures, avec un bouton pour réessayer", async () => {
    serve([NETWORK], () =>
      json(
        { type: "about:blank", title: "x", status: 404, code: "NOT_FOUND", correlation_id: "c" },
        404,
      ),
    );
    render(<TrainedModel />);
    expect(await screen.findByText(/Aucune mesure à cette date/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeVisible();
  });

  it("annonce les capteurs que le modèle ne connaît pas", async () => {
    serve([NETWORK], () => json({ ...FORECASTS, sensors_without_model: 3 }));
    render(<TrainedModel />);
    expect(
      await screen.findByText(/3 capteurs du réseau ne sont pas connus du modèle/),
    ).toBeVisible();
  });
});
