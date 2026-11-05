import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Alerts from "@/features/alerts/Alerts";
import { REFRESH_MS } from "@/features/alerts/useAlerts";
import { AuthContext } from "@/features/auth/AuthContext";
import type { Alert } from "@/services/alerte";
import type { Role } from "@/services/apiMetier";
import { setAccessToken } from "@/services/session";
import { ALERT, controlledStream, sseMessage } from "../../fixtures/alerts";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const problem = (status: number, code: string) =>
  json({ type: "about:blank", title: "Erreur", status, code, correlation_id: "corr-9" }, status);

const SECOND: Alert = {
  ...ALERT,
  alert_id: "9a3b2c10-5d6e-4f70-8a91-b2c3d4e5f607",
  road_segment_id: "ROAD_002",
  kind: "SENSOR_FAULT",
  severity: "INFO",
  opened_at: "2026-10-20T08:05:00Z",
};
const RESOLVED: Alert = {
  ...ALERT,
  alert_id: "0b9a7d2e-8a51-4c3b-b1c4-77aa66bb55cc",
  road_segment_id: "ROAD_003",
  state: "RESOLVED",
  resolution: "AUTO",
  resolved_at: "2026-10-20T08:20:00Z",
  opened_at: "2026-10-20T07:00:00Z",
  provenance: { source_type: "REAL_HISTORICAL", run_id: "h1", dataset_id: "paris" },
};

function withRole(role: Role | null, children: ReactNode) {
  const user = role
    ? {
        user_id: "7b0c2a3e-5f0e-4c43-9a43-1d6d6a3f0c11",
        username: "agent1",
        role,
        is_active: true,
        created_at: "2026-10-20T08:00:00Z",
      }
    : null;
  return (
    <AuthContext.Provider
      value={{ isAuthenticated: true, user, login: async () => undefined, logout: () => undefined }}
    >
      {children}
    </AuthContext.Provider>
  );
}

interface Server {
  stream: ReturnType<typeof controlledStream>;
  calls: string[];
  list: ReturnType<typeof vi.fn>;
}

/** L'API et le flux : la liste est rendue par `list`, le flux est alimenté par le test. */
function serve(
  items: Alert[] = [ALERT, SECOND, RESOLVED],
  extra: Record<string, (request: Request) => Response | Promise<Response>> = {},
): Server {
  const first = controlledStream();
  const streams = [first];
  const calls: string[] = [];
  const list = vi.fn(() => json({ items, next_cursor: null }));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const key = `${request.method} ${new URL(request.url).pathname}`;
    calls.push(key);
    if (key === "GET /api/v1/alerts") return list();
    if (key === "GET /api/v1/events/stream") {
      const next = streams.shift() ?? controlledStream();
      return next.response;
    }
    const handler = extra[key];
    if (!handler) throw new Error(`Appel non prévu : ${key}`);
    return handler(request);
  });
  return { stream: first, calls, list };
}

const rows = () => within(screen.getByRole("table")).getAllByRole("row").slice(1);

const cells = (row: HTMLElement) =>
  within(row)
    .getAllByRole("cell")
    .map((cell) => (cell.textContent ?? "").replace(/\s+/g, " ").trim());

describe("Alerts : les alertes en direct", () => {
  beforeEach(() => setAccessToken("jeton-d-essai"));
  afterEach(() => {
    vi.restoreAllMocks();
    setAccessToken(null);
  });

  it("affiche les alertes actives de la plus récente à la plus ancienne, avec leur provenance", async () => {
    serve();
    render(withRole("viewer", <Alerts />));

    await screen.findByRole("table");
    expect(rows()).toHaveLength(2); // l'alerte résolue est masquée par défaut
    expect(cells(rows()[0]).slice(0, 7)).toEqual([
      "20/10/2026 08:05",
      "ROAD_002",
      "Capteur muet",
      "Information",
      "Créée",
      "Cause inconnue",
      "Simulé Données simulées",
    ]);
    expect(cells(rows()[1])[1]).toBe("ROAD_001");
    expect(screen.getByText("2 alertes actives")).toBeInTheDocument();
  });

  it("annonce « En direct » une fois le flux ouvert", async () => {
    serve();
    render(withRole("viewer", <Alerts />));
    expect(await screen.findByText("En direct")).toHaveAttribute("role", "status");
  });

  it("une alerte créée apparaît sans rechargement, puis suit son cycle de vie jusqu'à la résolution", async () => {
    const server = serve([]);
    render(withRole("viewer", <Alerts />));
    await screen.findByText("Aucune alerte à afficher.");
    await screen.findByText("En direct");
    const listCalls = server.list.mock.calls.length;

    server.stream.push(sseMessage({}, "alerte-1-created"));
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(cells(rows()[0])[4]).toBe("Créée");
    expect(screen.getByText("1 alerte active")).toBeInTheDocument();

    server.stream.push(sseMessage({ state: "NOTIFIED" }, "alerte-1-notified"));
    await waitFor(() => expect(cells(rows()[0])[4]).toBe("Notifiée"));

    server.stream.push(
      sseMessage({ state: "RESOLVED", resolution: "AUTO", resolved_at: "2026-10-20T08:09:00Z" }),
    );
    await screen.findByText("Aucune alerte à afficher."); // résolue : sortie des alertes actives
    expect(screen.getByText("Aucune alerte active")).toBeInTheDocument();
    expect(server.list.mock.calls.length).toBe(listCalls); // aucun rechargement de la liste
  });

  it("montre aussi les alertes résolues, avec le mode de résolution, quand on le demande", async () => {
    serve();
    render(withRole("viewer", <Alerts />));
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Afficher"), "all");
    expect(rows()).toHaveLength(3);
    const resolved = rows().find((row) => within(row).queryByText("ROAD_003"));
    expect(cells(resolved!)[4]).toBe("Résolue (automatique)");
    expect(cells(resolved!)[6]).toBe("Données réelles (historique)"); // pas de pastille « Simulé »
  });

  it("dit qu'il n'y a pas d'alerte quand l'API n'en rend aucune", async () => {
    serve([]);
    render(withRole("viewer", <Alerts />));
    expect(await screen.findByText("Aucune alerte à afficher.")).toBeInTheDocument();
    expect(screen.getByText(/La circulation est normale/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Afficher"), "all");
    expect(screen.getByText("Aucune alerte n'a encore été émise.")).toBeInTheDocument();
  });

  it("dit l'erreur de chargement et propose de réessayer", async () => {
    const server = serve();
    // Le chargement est lancé deux fois (à l'ouverture, puis à l'ouverture du flux) : la panne dure.
    server.list.mockImplementation(() => problem(503, "UPSTREAM_UNAVAILABLE"));
    render(withRole("viewer", <Alerts />));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Les alertes n'ont pas pu être chargées.",
    );
    server.list.mockImplementation(() => json({ items: [ALERT], next_cursor: null }));
    await userEvent.click(screen.getByRole("button", { name: "Réessayer" }));
    await screen.findByRole("table");
  });

  it("un échec de rafraîchissement ne cache pas les alertes déjà affichées", async () => {
    const server = serve();
    render(withRole("viewer", <Alerts />));
    await screen.findByRole("table");
    server.list.mockReturnValue(problem(500, "INTERNAL_ERROR"));
    server.stream.end(); // reconnexion : la liste est relue, et échoue
    await waitFor(
      () => expect(server.calls.filter((c) => c === "GET /api/v1/events/stream").length).toBe(2),
      {
        timeout: 5000,
      },
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("à la reconnexion du flux, relit la liste : les événements d'une coupure ne sont pas rejoués", async () => {
    const server = serve([ALERT]);
    render(withRole("viewer", <Alerts />));
    await screen.findByRole("table");
    await screen.findByText("En direct");
    server.list.mockReturnValue(json({ items: [ALERT, SECOND], next_cursor: null }));
    server.stream.end();
    await screen.findByText("Flux interrompu : reconnexion en cours");
    await waitFor(() => expect(rows()).toHaveLength(2), { timeout: 5000 });
    expect(screen.getByText("En direct")).toBeInTheDocument();
  });

  it("la liste lue après l'événement ne ramène pas une alerte à un état antérieur", async () => {
    const server = serve([ALERT]);
    render(withRole("viewer", <Alerts />));
    await screen.findByText("En direct");
    server.stream.push(sseMessage({ state: "ACKNOWLEDGED", acknowledged_by: "u" }));
    await waitFor(() => expect(cells(rows()[0])[4]).toBe("Acquittée"));
    server.list.mockReturnValue(json({ items: [ALERT], next_cursor: null })); // lue plus tôt : CREATED
    server.stream.end();
    await waitFor(() => expect(server.list.mock.calls.length).toBeGreaterThan(2), {
      timeout: 5000,
    });
    expect(cells(rows()[0])[4]).toBe("Acquittée");
  });

  it("relit la liste à intervalle régulier : un événement manqué ne reste pas faux", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const server = serve([ALERT]);
      render(withRole("viewer", <Alerts />));
      await screen.findByRole("table");
      const before = server.list.mock.calls.length;
      server.list.mockReturnValue(json({ items: [ALERT, SECOND], next_cursor: null }));
      await vi.advanceTimersByTimeAsync(REFRESH_MS + 100);
      await waitFor(() => expect(rows()).toHaveLength(2));
      expect(server.list.mock.calls.length).toBeGreaterThan(before);
    } finally {
      vi.useRealTimers();
    }
  });

  describe("actions de l'opérateur", () => {
    it("un lecteur ne voit aucun bouton d'action", async () => {
      serve();
      render(withRole("viewer", <Alerts />));
      await screen.findByRole("table");
      expect(screen.queryByRole("button", { name: "Acquitter" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Résoudre" })).not.toBeInTheDocument();
    });

    it("sans compte lu, aucune action n'est proposée", async () => {
      serve();
      render(withRole(null, <Alerts />));
      await screen.findByRole("table");
      expect(screen.queryByRole("button", { name: "Acquitter" })).not.toBeInTheDocument();
    });

    it("un opérateur acquitte : l'alerte passe à « Acquittée » et le bouton disparaît", async () => {
      serve([ALERT], {
        "POST /api/v1/alerts/3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d10/acknowledge": () =>
          json({ ...ALERT, state: "ACKNOWLEDGED", acknowledged_by: "agent1" }),
      });
      render(withRole("operator", <Alerts />));
      await screen.findByRole("table");
      await userEvent.click(screen.getByRole("button", { name: "Acquitter" }));
      await waitFor(() => expect(cells(rows()[0])[4]).toBe("Acquittée"));
      expect(screen.queryByRole("button", { name: "Acquitter" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Résoudre" })).toBeInTheDocument();
    });

    it("un administrateur résout : l'alerte sort des alertes actives", async () => {
      serve([ALERT], {
        "POST /api/v1/alerts/3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d10/resolve": () =>
          json({
            ...ALERT,
            state: "RESOLVED",
            resolution: "MANUAL",
            resolved_at: "2026-10-20T08:30:00Z",
          }),
      });
      render(withRole("admin", <Alerts />));
      await screen.findByRole("table");
      await userEvent.click(screen.getByRole("button", { name: "Résoudre" }));
      await screen.findByText("Aucune alerte à afficher.");
    });

    it("dit pourquoi une action est refusée (alerte déjà résolue) et garde l'alerte", async () => {
      serve([ALERT], {
        "POST /api/v1/alerts/3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d10/acknowledge": () =>
          problem(409, "INVALID_STATE_TRANSITION"),
      });
      render(withRole("operator", <Alerts />));
      await screen.findByRole("table");
      await userEvent.click(screen.getByRole("button", { name: "Acquitter" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Cette alerte ne peut pas passer dans cet état.",
      );
      expect(cells(rows()[0])[4]).toBe("Créée");
      expect(screen.getByRole("button", { name: "Acquitter" })).toBeEnabled();
    });
  });

  it("annonce la perte du flux, sans cacher les alertes", async () => {
    const server = serve();
    render(withRole("viewer", <Alerts />));
    await screen.findByText("En direct");
    server.stream.fail(new TypeError("réseau coupé"));
    expect(await screen.findByText("Flux interrompu : reconnexion en cours")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
