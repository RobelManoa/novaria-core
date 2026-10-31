import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Forecasts from "@/features/forecasts/Forecasts";
import type { Forecast, Indicator } from "@/services/traitement";

// Réponses construites d'après le contrat (types générés : un champ manquant ou d'un autre type ne compile pas).
// L'API réelle n'implémente pas encore /forecasts : ces tests prouvent le rendu, pas le serveur.

const SIMULATED = {
  source_type: "SIMULATED",
  run_id: "run-demo",
  scenario_id: "demo",
  seed: 7,
} as const;
const ISSUED = "2026-10-30T08:00:00Z";

function forecast(
  segment: string,
  horizonMin: number,
  ratio: number,
  overrides: Partial<Forecast> = {},
): Forecast {
  const target = new Date(Date.parse(ISSUED) + horizonMin * 60_000);
  return {
    road_segment_id: segment,
    issued_at: ISSUED,
    horizon_min: horizonMin,
    target_time: target.toISOString().replace(".000Z", "Z"),
    predicted_speed_ratio: ratio,
    predicted_state: "FREE_FLOW",
    model: { kind: "REFERENCE", name: "persistance", version: "v0", run_id: null },
    provenance: SIMULATED,
    ...overrides,
  };
}

function indicator(segment: string, start: string, ratio: number | null): Indicator {
  return {
    indicator_id: `run-demo:${segment}:300:${Date.parse(start)}`,
    road_segment_id: segment,
    intersection_id: "INT_01",
    window_start: start,
    window_size_s: 300,
    vehicle_count: 10,
    flow_veh_per_min: 2,
    average_speed_kmh: ratio === null ? null : ratio * 50,
    speed_ratio: ratio,
    sample_count: 6,
    expected_sample_count: 6,
    congestion_state: "FREE_FLOW",
    classifier_version: "regles-v0",
    provenance: SIMULATED,
  };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const problem = (status: number, code: string) =>
  json({ type: "about:blank", title: "Erreur", status, code, correlation_id: "corr-9" }, status);

/** Des prévisions pour deux tronçons, à tous les horizons : ratio = 0,5 + horizon / 1000. */
const ratioAt = (segment: string, horizon: number) =>
  Math.round((segment === "ROAD_002" ? 0.3 : 0.5) * 1000 + horizon) / 1000;

interface Api {
  forecasts?: (url: URL) => Response;
  indicators?: (url: URL) => Response;
}

function serve({ forecasts, indicators }: Api = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL((input as Request).url);
    if (url.pathname === "/api/v1/forecasts") {
      if (forecasts) return forecasts(url);
      const horizon = Number(url.searchParams.get("horizon_min") ?? 15);
      const requested = url.searchParams.getAll("road_segment_id");
      const segments = requested.length ? requested : ["ROAD_001", "ROAD_002"];
      return json({
        items: segments.map((segment) => forecast(segment, horizon, ratioAt(segment, horizon))),
      });
    }
    if (url.pathname === "/api/v1/indicators") {
      return indicators ? indicators(url) : json({ items: [], next_cursor: null });
    }
    throw new Error(`Appel non prévu : ${url.pathname}`);
  });
}

/** Les paires « terme → valeur » de la carte du modèle. */
const modelCard = async () => {
  const card = await screen.findByRole("region", { name: "Modèle" });
  const terms = Array.from(card.querySelectorAll("dt"), (term) => (term.textContent ?? "").trim());
  const values = Array.from(card.querySelectorAll("dd"), (value) =>
    (value.textContent ?? "").trim(),
  );
  return {
    fields: Object.fromEntries(terms.map((term, i) => [term, values[i]])),
    text: (card.textContent ?? "").replace(/\s+/g, " "),
  };
};

const table = () => {
  const region = screen.getByRole("region", { name: "Prévu contre observé" });
  return Array.from(within(region).getAllByRole("row").slice(1), (row) =>
    Array.from(row.querySelectorAll("th, td"), (cell) =>
      (cell.textContent ?? "").replace(/\s+/g, " ").trim(),
    ),
  );
};

describe("Forecasts : la page affiche la prévision renvoyée par l'API", () => {
  afterEach(() => vi.restoreAllMocks());

  it("montre, pour chaque horizon, le ratio prévu et l'instant prévu rendus par l'API", async () => {
    serve();
    render(<Forecasts />);

    await screen.findByRole("region", { name: "Prévu contre observé" });
    expect(table()).toEqual(
      [5, 10, 15, 30, 45, 60].map((horizon) => {
        const target = new Date(Date.parse(ISSUED) + horizon * 60_000);
        const hh = String(target.getUTCHours()).padStart(2, "0");
        const mm = String(target.getUTCMinutes()).padStart(2, "0");
        return [
          String(horizon),
          `30/10/2026 ${hh}:${mm}`,
          // Le ratio prévu est écrit avec les trois décimales de l'API.
          ratioAt("ROAD_001", horizon).toFixed(3).replace(".", ","),
          "Fluide",
          "Non disponible",
        ];
      }),
    );
  });

  it("change de tronçon : les valeurs affichées suivent celles de l'API pour ce tronçon", async () => {
    const spy = serve();
    render(<Forecasts />);
    await screen.findByRole("region", { name: "Prévu contre observé" });

    await userEvent.selectOptions(screen.getByLabelText("Tronçon"), "ROAD_002");

    await waitFor(() => expect(table()[2][2]).toBe("0,315")); // 0,300 + 15 / 1000
    const asked = spy.mock.calls
      .map(([request]) => new URL((request as Request).url))
      .filter(
        (url) =>
          url.pathname === "/api/v1/forecasts" &&
          url.searchParams.getAll("road_segment_id").includes("ROAD_002"),
      );
    expect(asked.map((url) => url.searchParams.get("horizon_min"))).toEqual([
      "5",
      "10",
      "15",
      "30",
      "45",
      "60",
    ]);
  });

  it("affiche le modèle de référence tel que l'API le décrit, sans inventer d'entraînement", async () => {
    serve();
    render(<Forecasts />);

    const { fields, text } = await modelCard();
    expect(fields).toEqual({
      Type: "Modèle de référence (persistance ou moyenne glissante)",
      Nom: "persistance",
      Version: "v0",
      "Exécution d'entraînement": "—",
      "Dernier entraînement": "Sans objet : modèle de référence, pas d'entraînement",
      "Métrique du modèle": "Sans objet : modèle de référence, pas d'entraînement",
      "Origine des données": "Données simulées · exécution run-demo · scénario demo",
      "Prévision émise le": "30/10/2026 08:00 (UTC)",
    });
    expect(text).toContain("Aucun modèle entraîné n'a battu la référence");
    expect(text).not.toContain("Non communiqué");
  });

  it("dit que la date d'entraînement et la métrique ne sont pas fournies quand le modèle est entraîné", async () => {
    serve({
      forecasts: (url) =>
        json({
          items: [
            forecast("ROAD_001", Number(url.searchParams.get("horizon_min")), 0.5, {
              model: {
                kind: "MODEL",
                name: "gradient-boosting",
                version: "1.2.0",
                run_id: "run-77",
              },
            }),
          ],
        }),
    });
    render(<Forecasts />);

    const { fields, text } = await modelCard();
    expect(fields).toMatchObject({
      Type: "Modèle entraîné",
      Nom: "gradient-boosting",
      Version: "1.2.0",
      "Exécution d'entraînement": "run-77",
      "Dernier entraînement": "Non communiqué par l'API",
      "Métrique du modèle": "Non communiqué par l'API",
    });
    expect(text).toContain("Un modèle entraîné sur le simulateur apprend le simulateur");
  });

  it("compare une prévision à la valeur observée quand son instant est passé", async () => {
    serve({
      indicators: () =>
        json({
          items: [
            // Fenêtre 08:15 → 08:20 : contient l'instant prévu à +15 min (08:15).
            indicator("ROAD_001", "2026-10-30T08:15:00Z", 0.5),
            indicator("ROAD_001", "2026-10-30T07:55:00Z", 0.48),
          ],
          next_cursor: null,
        }),
    });
    render(<Forecasts />);
    await screen.findByRole("region", { name: "Prévu contre observé" });

    const row15 = table().find((row) => row[0] === "15") as string[];
    // Prévu 0,515 ; observé 0,500 ; écart +0,015.
    expect(row15.slice(2)).toEqual(["0,515", "Fluide", "0,500", "0,015"]);
    // Les instants plus tardifs que la dernière fenêtre observée ne sont « pas encore observés ».
    const row60 = table().find((row) => row[0] === "60") as string[];
    expect(row60.at(-1)).toBe("Pas encore observé");
  });

  it("trace l'observé et le prévu dans le même graphique, avec leurs valeurs dans un tableau", async () => {
    serve({
      indicators: () =>
        json({ items: [indicator("ROAD_001", "2026-10-30T07:55:00Z", 0.48)], next_cursor: null }),
    });
    render(<Forecasts />);

    const chart = await screen.findByRole("img", { name: /Ratio de vitesse/ });
    expect(chart).toHaveAccessibleName(
      /observé de 07:55 à 07:55 UTC \(1 valeurs\) ; 6 valeurs prévues jusqu'à 09:00 UTC/,
    );
  });
});

describe("Forecasts : états de chargement, vide et erreur", () => {
  afterEach(() => vi.restoreAllMocks());

  it("annonce le chargement", () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    render(<Forecasts />);

    expect(screen.getByRole("status")).toHaveTextContent("Chargement des prévisions…");
  });

  it("dit que la route n'est pas servie quand l'API répond 404", async () => {
    serve({ forecasts: () => problem(404, "NOT_FOUND") });
    render(<Forecasts />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("n'est pas encore disponible sur ce serveur");
    expect(alert).toHaveTextContent("/api/v1/forecasts");
    expect(alert).not.toHaveTextContent("Élément introuvable");
  });

  it("rend le message du contrat quand aucune prévision n'est disponible (503)", async () => {
    serve({ forecasts: () => problem(503, "FORECAST_UNAVAILABLE") });
    render(<Forecasts />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Aucune prévision n'est disponible pour le moment.");
    expect(alert).toHaveTextContent("Référence à citer : corr-9.");
  });

  it("relit l'API au clic sur « Réessayer »", async () => {
    let calls = 0;
    serve({
      forecasts: (url) => {
        calls += 1;
        if (calls === 1) return problem(503, "FORECAST_UNAVAILABLE");
        return json({
          items: [forecast("ROAD_001", Number(url.searchParams.get("horizon_min")), 0.5)],
        });
      },
    });
    render(<Forecasts />);

    await userEvent.click(await screen.findByRole("button", { name: "Réessayer" }));

    expect(await screen.findByRole("region", { name: "Prévu contre observé" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("affiche l'état vide quand l'API ne rend aucune prévision", async () => {
    serve({ forecasts: () => json({ items: [] }) });
    render(<Forecasts />);

    expect(await screen.findByRole("status")).toHaveTextContent("Aucune prévision disponible");
  });

  it("affiche l'état vide d'un tronçon sans prévision", async () => {
    serve({
      forecasts: (url) =>
        url.searchParams.getAll("road_segment_id").length
          ? json({ items: [] })
          : json({ items: [forecast("ROAD_001", 15, 0.5)] }),
    });
    render(<Forecasts />);

    expect(await screen.findByText("Aucune prévision pour ce tronçon")).toBeInTheDocument();
    expect(screen.getByLabelText("Tronçon")).toBeInTheDocument();
  });

  it("prévient qu'il n'y a pas d'observé et propose les fenêtres de 5 minutes", async () => {
    const spy = serve();
    render(<Forecasts />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Essayer les fenêtres de 5 minutes" }),
    );

    await waitFor(() =>
      expect(screen.getByLabelText("Taille des fenêtres observées")).toHaveValue("300"),
    );
    const lastList = spy.mock.calls
      .map(([request]) => new URL((request as Request).url))
      .filter((url) => url.pathname === "/api/v1/indicators")
      .at(-1);
    expect(lastList?.searchParams.get("window_size_s")).toBe("300");
  });

  it("prévient quand la lecture de l'observé est tronquée", async () => {
    serve({
      indicators: () =>
        json({ items: [indicator("ROAD_001", "2026-10-30T07:55:00Z", 0.5)], next_cursor: "suite" }),
    });
    render(<Forecasts />);

    expect(await screen.findByRole("note")).toHaveTextContent("s'arrête à 1 500 indicateurs");
  });
});
