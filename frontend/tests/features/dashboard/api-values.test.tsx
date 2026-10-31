import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "@/features/dashboard/Dashboard";
import fixtureText from "../../fixtures/dashboard-api.json?raw";

/**
 * Critère de FE-04 : « les valeurs affichées correspondent à celles de l'API ».
 *
 * La page est rendue sur des réponses RÉELLES de l'API (enregistrées par scripts/dev/dashboard_fixture.py sur la
 * pile locale : PostgreSQL, vue dwh.v_indicator, service traitement). Les valeurs attendues viennent du même
 * script, calculées en Python sans rien reprendre du code du front-end. Ce test ne recalcule donc rien : il
 * compare l'écran à ces valeurs, en écrivant les nombres et les dates par découpage de texte (pas par le code
 * de mise en forme de l'application).
 */

interface Expected {
  meta: {
    source_type: string;
    run_id: string;
    indicator_count: number;
    segment_count: number;
    first_window: string;
    last_window: string;
  };
  cards: { speed: string; vehicles: string; flow: string; congested: string };
  speed_series: Array<[string, string | null]>;
  flow_series: Array<[string, string | null]>;
  states: Record<"CONGESTED" | "SLOW" | "FREE_FLOW" | "UNKNOWN", number>;
  segments: Array<{
    road_segment_id: string;
    intersection_id: string;
    state: string;
    speed: string | null;
    flow: string;
    vehicles: string;
    window_start: string;
  }>;
}

interface Scenario {
  name: string;
  requests: Array<{ query: Record<string, string>; response: unknown }>;
  expected: Expected | null;
}

const scenarios = (JSON.parse(fixtureText) as { scenarios: Scenario[] }).scenarios;
const scenario = (name: string) => scenarios.find((item) => item.name === name) as Scenario;

/** Sert les réponses enregistrées ; toute requête que l'API n'a pas vue lève une erreur qui fait échouer le test. */
function serveRecordedApi() {
  const served = new Set<string>();
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL((input as Request).url);
    const query = Object.fromEntries(url.searchParams);
    const key = JSON.stringify([url.pathname, Object.entries(query).sort()]);
    const match = scenarios
      .flatMap((item) => item.requests)
      .find(
        (recorded) =>
          url.pathname === "/api/v1/indicators" &&
          JSON.stringify([url.pathname, Object.entries(recorded.query).sort()]) === key,
      );
    if (!match) throw new Error(`Requête sans réponse enregistrée : ${url.pathname}${url.search}`);
    served.add(key);
    return new Response(JSON.stringify(match.response), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  return { spy, served };
}

// --- Écriture des valeurs attendues, indépendante du code de l'application -------------------------------------

// `\s` couvre aussi les espaces insécables (U+00A0, U+202F) que Intl met dans « 16 171 ».
const normalize = (text: string | null) => (text ?? "").replace(/\s+/g, " ").trim();

/** « 16171.5 » → « 16 171,5 » : séparateur de milliers (espace) et virgule décimale. */
function french(value: string): string {
  const [integer, decimals] = value.split(".");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return decimals === undefined ? grouped : `${grouped},${decimals}`;
}

/** « 2026-10-30T08:55:00Z » → « 08:55 » (l'heure UTC de la date, lue dans le texte). */
const hhmm = (iso: string) => iso.slice(11, 16);

/** « 2026-10-30T08:55:00Z » → « 30/10/2026 08:55 ». */
const ddmmyyyy = (iso: string) =>
  `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)} ${hhmm(iso)}`;

const dash = "—";
const shown = (value: string | null) => (value === null ? dash : french(value));

// --- Lecture de l'écran ------------------------------------------------------------------------------------------

function cardValue(label: string): string {
  const region = screen.getByRole("region", { name: "Indicateurs clés" });
  const card = within(region).getByText(label, { selector: "p" });
  return normalize(card.nextElementSibling?.textContent ?? null);
}

function chartRows(title: string): Array<[string, string]> {
  // Le texte propre du <figcaption> est le titre ; l'unité est dans un <span>.
  const caption = screen.getByText(title, { selector: "figcaption" });
  const figure = caption.closest("figure") as HTMLElement;
  return within(figure)
    .getAllByRole("row", { hidden: true })
    .slice(1) // l'en-tête
    .map((row) => {
      const cells = within(row).getAllByRole("cell", { hidden: true });
      const [time] = within(row).getAllByRole("rowheader", { hidden: true });
      return [normalize(time.textContent), normalize(cells[0].textContent)];
    });
}

function segmentRows(): string[][] {
  const region = screen.getByRole("region", { name: "Détail par tronçon" });
  return within(region)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      Array.from(row.querySelectorAll("th, td"), (cell) => normalize(cell.textContent)),
    );
}

function expectScreenToMatch(expected: Expected) {
  // Cartes
  expect(cardValue("Vitesse moyenne")).toBe(`${french(expected.cards.speed)} km/h`);
  expect(cardValue("Véhicules comptés")).toBe(french(expected.cards.vehicles));
  expect(cardValue("Débit moyen")).toBe(`${french(expected.cards.flow)} véh/min`);
  expect(cardValue("Tronçons congestionnés")).toBe(expected.cards.congested);

  // Graphiques : une ligne du tableau « Voir les valeurs » par fenêtre, heure et valeur
  expect(chartRows("Vitesse moyenne")).toEqual(
    expected.speed_series.map(([window, value]) => [hhmm(window), shown(value)]),
  );
  expect(chartRows("Débit cumulé")).toEqual(
    expected.flow_series.map(([window, value]) => [hhmm(window), shown(value)]),
  );

  // Répartition des états
  const statesRegion = screen.getByRole("region", { name: "État des tronçons" });
  const legend = within(statesRegion)
    .getAllByRole("listitem")
    .map((item) => normalize(item.textContent));
  expect(legend).toEqual([
    `Congestionné ${expected.states.CONGESTED}`,
    `Ralenti ${expected.states.SLOW}`,
    `Fluide ${expected.states.FREE_FLOW}`,
    `Inconnu ${expected.states.UNKNOWN}`,
  ]);

  // Détail par tronçon : valeurs brutes de l'API
  expect(segmentRows()).toEqual(
    expected.segments.map((segment) => [
      segment.road_segment_id,
      segment.intersection_id,
      segment.state,
      shown(segment.speed),
      french(segment.flow),
      french(segment.vehicles),
      ddmmyyyy(segment.window_start),
    ]),
  );

  // Origine et étendue des données
  const meta = normalize(document.body.textContent);
  expect(meta).toContain("Données simulées");
  expect(meta).toContain(`exécution ${expected.meta.run_id}`);
  expect(meta).toContain(
    `fenêtres du ${ddmmyyyy(expected.meta.first_window)} au ${ddmmyyyy(expected.meta.last_window)} (UTC)`,
  );
  expect(meta).toContain(
    `${french(String(expected.meta.indicator_count))} indicateurs · ${expected.meta.segment_count} tronçons`,
  );
}

describe("valeurs affichées et réponses de l'API", () => {
  afterEach(() => vi.restoreAllMocks());

  it("les enregistrements portent des valeurs réelles : plusieurs tronçons, fenêtres et zones", () => {
    const network = scenario("reseau-1h-5min").expected as Expected;
    expect(network.meta.segment_count).toBe(24);
    expect(network.meta.indicator_count).toBe(24 * 12);
    expect(scenario("zone-INT_02-6h-5min").expected?.meta.segment_count).toBe(4);
    expect(scenario("defaut-vide").expected).toBeNull();
  });

  it("tout le réseau, dernière heure, fenêtres de 5 minutes", async () => {
    const { served } = serveRecordedApi();
    render(<Dashboard />);
    // La page s'ouvre sur les fenêtres d'une minute (défaut de l'API) : le jeu de démonstration n'en a pas.
    await userEvent.click(
      await screen.findByRole("button", { name: "Essayer les fenêtres de 5 minutes" }),
    );
    await screen.findByRole("region", { name: "Indicateurs clés" });

    expectScreenToMatch(scenario("reseau-1h-5min").expected as Expected);
    for (const recorded of scenario("reseau-1h-5min").requests) {
      expect(served).toContain(
        JSON.stringify(["/api/v1/indicators", Object.entries(recorded.query).sort()]),
      );
    }
  });

  it("une zone (carrefour INT_02) sur 6 heures", async () => {
    const { served } = serveRecordedApi();
    render(<Dashboard />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Essayer les fenêtres de 5 minutes" }),
    );
    await screen.findByRole("region", { name: "Indicateurs clés" });

    await userEvent.selectOptions(screen.getByLabelText("Période"), "6");
    await userEvent.selectOptions(screen.getByLabelText("Zone"), "INT_02");
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Détail par tronçon" })).toBeInTheDocument(),
    );
    await waitFor(() => expect(segmentRows()).toHaveLength(4));

    expectScreenToMatch(scenario("zone-INT_02-6h-5min").expected as Expected);
    for (const recorded of scenario("zone-INT_02-6h-5min").requests) {
      expect(served).toContain(
        JSON.stringify(["/api/v1/indicators", Object.entries(recorded.query).sort()]),
      );
    }
  });
});
