import { render } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { vi } from "vitest";
import App from "@/app/App";
import { routes } from "@/app/router";
import { setAccessToken } from "@/services/session";

export const HEALTH = { status: "ok", version: "0.1.0", revision: "abc123", environment: "test" };
export const USER = {
  user_id: "7b0c2a3e-5f0e-4c43-9a43-1d6d6a3f0c11",
  username: "operateur1",
  role: "operator",
  is_active: true,
  created_at: "2026-10-20T08:00:00Z",
};
export const TOKEN = { access_token: "jeton-de-test", token_type: "bearer", expires_in: 1800 };

type Handler = (request: Request) => Response | Promise<Response>;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

/** Réponses par défaut, par « MÉTHODE /chemin » ; un test les remplace une à une avec `overrides`. */
const DEFAULTS: Record<string, Handler> = {
  "GET /api/v1/health": () => json(HEALTH),
  "GET /api/v1/auth/me": () => json(USER),
  // Le tableau de bord (page d'accueil) lit les indicateurs : sans donnée, il affiche son état vide.
  "GET /api/v1/indicators": () => json({ items: [], next_cursor: null }),
  "POST /api/v1/auth/login": () => json(TOKEN),
};

/**
 * Remplace fetch : l'application ne doit jamais appeler le réseau pendant les tests. Une requête sans
 * réponse prévue échoue, ce qui révèle tout appel inattendu.
 */
export function mockApi(overrides: Record<string, Handler> = {}) {
  const handlers = { ...DEFAULTS, ...overrides };
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const key = `${request.method} ${new URL(request.url).pathname}`;
    const handler = handlers[key];
    if (!handler) throw new Error(`Appel d'API non prévu dans le test : ${key}`);
    return handler(request);
  });
}

/** Sonde de santé seule (les tests de la coque n'ont pas besoin d'autre réponse). */
export function mockHealth(status = 200) {
  return mockApi({ "GET /api/v1/health": () => json(HEALTH, status) });
}

/** Ouvre une session comme après une connexion réussie. */
export function signIn(expiresInSeconds = 1800) {
  setAccessToken(TOKEN.access_token, expiresInSeconds);
}

interface RenderAppOptions {
  /** Session ouverte avant le rendu (par défaut oui : les pages protégées sont alors accessibles). */
  signedIn?: boolean;
  /** Réponses d'API remplacées pour ce test. */
  api?: Record<string, Handler>;
}

/** Monte l'application complète sur un routeur mémoire, à l'adresse demandée. */
export function renderApp(path = "/", { signedIn = true, api }: RenderAppOptions = {}) {
  const fetchSpy = mockApi(api);
  if (signedIn) signIn();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(<App router={router} />);
  return { router, fetchSpy, ...view };
}
