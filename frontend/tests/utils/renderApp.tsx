import { render } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { vi } from "vitest";
import App from "@/app/App";
import { routes } from "@/app/router";

const HEALTH = { status: "ok", version: "0.1.0", revision: "abc123", environment: "test" };

/** Remplace fetch : l'application ne doit jamais appeler le réseau pendant les tests. */
export function mockHealth(status = 200) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(new Response(JSON.stringify(HEALTH), { status })));
}

/** Monte l'application complète sur un routeur mémoire, à l'adresse demandée. */
export function renderApp(path = "/") {
  mockHealth();
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(<App router={router} />);
  return { router, ...view };
}
