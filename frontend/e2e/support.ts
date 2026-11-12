import { readFileSync } from "node:fs";
import type { Page, Route } from "@playwright/test";

// API simulée du parcours de bout en bout. Les réponses du tableau de bord sont les réponses RÉELLES de l'API
// (enregistrées par scripts/dev/dashboard_fixture.py), les mêmes que celles des tests de composants : un écart
// entre ce que l'API a répondu et ce que l'écran affiche fait échouer le parcours.

export const USERNAME = "operateur1";
export const PASSWORD = "mot-de-passe-e2e";
export const TOKEN = "jeton-e2e";

export interface Expected {
  meta: { run_id: string; indicator_count: number; segment_count: number };
  cards: { speed: string; vehicles: string; flow: string; congested: string };
  segments: Array<{ road_segment_id: string; intersection_id: string; state: string }>;
}

interface Scenario {
  name: string;
  requests: Array<{ query: Record<string, string>; response: unknown }>;
  expected: Expected | null;
}

const fixture = JSON.parse(
  readFileSync(new URL("../tests/fixtures/dashboard-api.json", import.meta.url), "utf8"),
) as { scenarios: Scenario[] };

export const scenario = (name: string): Scenario => {
  const found = fixture.scenarios.find((item) => item.name === name);
  if (!found) throw new Error(`Scénario enregistré introuvable : ${name}`);
  return found;
};

/** « 16171.5 » → « 16 171,5 » : séparateur de milliers (espace) et virgule décimale, écrit sans le code de l'application. */
export function french(value: string): string {
  const [integer, decimals] = value.split(".");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return decimals === undefined ? grouped : `${grouped},${decimals}`;
}

export interface ApiCall {
  method: string;
  path: string;
  query: Record<string, string>;
  authorization: string | null;
}

export interface FakeApi {
  /** Tous les appels reçus, dans l'ordre. */
  calls: ApiCall[];
  /** Appels sans réponse prévue (le test doit vérifier qu'il n'y en a aucun). */
  unexpected: string[];
  /**
   * Lectures d'indicateurs que l'API n'a jamais enregistrées (une combinaison de filtres intermédiaire, quand on
   * change la période puis la zone). Elles reçoivent un 503, comme une panne, et le test dit lesquelles il attend.
   */
  unrecordedIndicators: Array<Record<string, string>>;
}

interface Options {
  /** Sert une erreur 503 aux `n` premières lectures d'indicateurs (pour éprouver « Réessayer »). */
  indicatorFailures?: number;
  /** Refuse le jeton à `GET /auth/me` : session expirée côté serveur. */
  rejectToken?: boolean;
}

const problem = (status: number, code: string) => ({
  status,
  contentType: "application/problem+json",
  body: JSON.stringify({
    type: "about:blank",
    title: "Erreur",
    status,
    code,
    correlation_id: "e2e-corr",
  }),
});
const ok = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const USER = {
  user_id: "7b0c2a3e-5f0e-4c43-9a43-1d6d6a3f0c11",
  username: USERNAME,
  role: "operator",
  is_active: true,
  created_at: "2026-10-20T08:00:00Z",
};

/** Installe l'API simulée sur la page. Toute requête `/api/` passe par ici ; rien ne sort vers le réseau. */
export async function installFakeApi(page: Page, options: Options = {}): Promise<FakeApi> {
  const api: FakeApi = { calls: [], unexpected: [], unrecordedIndicators: [] };
  let failuresLeft = options.indicatorFailures ?? 0;
  const recorded = fixture.scenarios.flatMap((item) => item.requests);

  await page.route("**/api/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const query = Object.fromEntries(url.searchParams);
    const authorization = (await request.headerValue("authorization")) ?? null;
    api.calls.push({ method: request.method(), path: url.pathname, query, authorization });
    const authorized = authorization === `Bearer ${TOKEN}`;
    const key = `${request.method()} ${url.pathname}`;

    if (key === "GET /api/v1/health") {
      return route.fulfill(
        ok({ status: "ok", version: "0.1.0", revision: "e2e", environment: "e2e" }),
      );
    }
    if (key === "POST /api/v1/auth/login") {
      const body = request.postDataJSON() as { username?: string; password?: string };
      if (body.username === USERNAME && body.password === PASSWORD) {
        return route.fulfill(ok({ access_token: TOKEN, token_type: "bearer", expires_in: 1800 }));
      }
      return route.fulfill(problem(401, "INVALID_CREDENTIALS"));
    }
    if (!authorized || options.rejectToken) {
      // Toute autre route exige le jeton, comme la passerelle.
      return route.fulfill(problem(401, "UNAUTHENTICATED"));
    }
    if (key === "GET /api/v1/auth/me") return route.fulfill(ok(USER));
    if (key === "GET /api/v1/indicators") {
      if (failuresLeft > 0) {
        failuresLeft -= 1;
        return route.fulfill(problem(503, "UPSTREAM_UNAVAILABLE"));
      }
      const wanted = JSON.stringify(Object.entries(query).sort());
      const match = recorded.find(
        (item) => JSON.stringify(Object.entries(item.query).sort()) === wanted,
      );
      if (match) return route.fulfill(ok(match.response));
      api.unrecordedIndicators.push(query);
      return route.fulfill(problem(503, "UPSTREAM_UNAVAILABLE"));
    }
    if (key === "GET /api/v1/alerts") return route.fulfill(ok({ items: [], next_cursor: null }));
    if (key === "GET /api/v1/events/stream") {
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: ": e2e\n\n" });
    }
    api.unexpected.push(`${key}${url.search}`);
    return route.fulfill(problem(500, "INTERNAL_ERROR"));
  });
  return api;
}
