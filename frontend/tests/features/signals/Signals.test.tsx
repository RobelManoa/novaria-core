import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Signals from "@/features/signals/Signals";
import type { SignalCommand, SignalState } from "@/services/reponse";
import { setAccessToken } from "@/services/session";
import {
  COMMAND,
  REFUSED_COMMAND,
  SIGNAL,
  SIGNAL_2,
  json,
  problem,
  withRole,
} from "../../fixtures/signals";

/** Les routes du service de réponse, rendues par des doublures que chaque test peut remplacer. */
function serve(items: SignalState[] = [SIGNAL, SIGNAL_2], history: SignalCommand[] = [COMMAND]) {
  const calls: string[] = [];
  const signals = vi.fn(() => json({ items }));
  const commands = vi.fn<(request: Request) => Response>(() =>
    json({ items: history, next_cursor: null }),
  );
  const post = vi.fn<(body: unknown, path: string) => Response>(() => json(COMMAND, 202));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    calls.push(`${request.method} ${path}`);
    if (request.method === "GET" && path === "/api/v1/signals") return signals();
    if (request.method === "GET" && /\/commands$/.test(path)) return commands(request);
    if (request.method === "POST" && /\/commands$/.test(path)) {
      return post(await request.clone().json(), path);
    }
    throw new Error(`Appel non prévu : ${request.method} ${path}`);
  });
  return { signals, commands, post, calls };
}

describe("Signals : l'état des feux", () => {
  beforeEach(() => setAccessToken("jeton-d-essai"));
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    setAccessToken(null);
  });

  it("affiche chaque carrefour avec son mode, son signal, sa phase et sa provenance", async () => {
    serve();
    render(withRole("viewer", <Signals />));

    const first = await screen.findByRole("article", { name: "INT_01" });
    expect(within(first).getByText("Automatique")).toBeInTheDocument();
    expect(within(first).getByText("Vert : Nord, Sud")).toBeInTheDocument();
    expect(within(first).getByTestId("current-phase")).toHaveTextContent("P1");
    expect(within(first).getByText("Simulé")).toBeInTheDocument();
    expect(within(first).getByText("Recommandation")).toBeInTheDocument();
    const plan = within(first).getByRole("list", { name: "Plan du carrefour INT_01" });
    expect(within(plan).getAllByRole("listitem")).toHaveLength(2);
    expect(within(plan).getByText("P1").closest("li")).toHaveAttribute("aria-current", "step");

    const second = screen.getByRole("article", { name: "INT_02" });
    expect(within(second).getByText("Plan fixe (mode dégradé)")).toBeInTheDocument();
    expect(within(second).getByText("Tout au rouge (dégagement)")).toBeInTheDocument();
    expect(screen.getByText(/En direct · mis à jour/)).toHaveAttribute("role", "status");
  });

  it("relit l'état à intervalle fixe : un changement de phase apparaît sans rechargement", async () => {
    const server = serve();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(withRole("viewer", <Signals />));
    await screen.findByRole("article", { name: "INT_01" });

    server.signals.mockImplementation(() =>
      json({
        items: [{ ...SIGNAL, current_phase_id: "P2", green_approaches: ["E", "W"] }, SIGNAL_2],
      }),
    );
    await vi.advanceTimersByTimeAsync(3_100);
    await waitFor(() =>
      expect(
        within(screen.getByRole("article", { name: "INT_01" })).getByTestId("current-phase"),
      ).toHaveTextContent("P2"),
    );
    expect(screen.getByText("Vert : Est, Ouest")).toBeInTheDocument();
  });

  it("garde les dernières valeurs et le dit quand une relecture échoue", async () => {
    const server = serve();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(withRole("viewer", <Signals />));
    await screen.findByRole("article", { name: "INT_01" });

    server.signals.mockImplementation(() => problem(503, "UPSTREAM_UNAVAILABLE"));
    await vi.advanceTimersByTimeAsync(3_100);
    expect(await screen.findByText(/Connexion perdue/)).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "INT_01" })).toBeInTheDocument();
  });

  it("dit l'erreur de chargement et propose de réessayer", async () => {
    const server = serve();
    server.signals.mockImplementation(() => problem(503, "UPSTREAM_UNAVAILABLE"));
    render(withRole("viewer", <Signals />));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "L'état des feux n'a pas pu être chargé.",
    );
    server.signals.mockImplementation(() => json({ items: [SIGNAL] }));
    await userEvent.click(screen.getByRole("button", { name: "Réessayer" }));
    await screen.findByRole("article", { name: "INT_01" });
  });

  it("dit qu'aucun carrefour n'est piloté quand le service n'en rend aucun", async () => {
    serve([]);
    render(withRole("viewer", <Signals />));
    expect(await screen.findByText("Aucun carrefour à feux.")).toBeInTheDocument();
  });

  it("le lecteur ne voit pas le formulaire de commande, mais voit l'historique", async () => {
    serve();
    render(withRole("viewer", <Signals />));
    expect(await screen.findByText(/réservée aux opérateurs/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Préparer la commande" })).toBeNull();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Vous")).toBeInTheDocument();
  });

  it("l'historique montre qui a commandé quoi, pourquoi, et le refus des garde-fous", async () => {
    serve([SIGNAL], [COMMAND, REFUSED_COMMAND]);
    render(withRole("viewer", <Signals />));
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    const text = (row: HTMLElement) => (row.textContent ?? "").replace(/\s+/g, " ").trim();
    expect(text(rows[0])).toBe(
      "20/10/2026 08:10VousImposer une phaseP230 sÉvacuation après incident confirméAppliquée",
    );
    expect(text(rows[1])).toContain("Refusée Durée sous le minimum de sécurité (10 s)");
    expect(within(rows[1]).getByText("cdd610fe…")).toHaveAttribute(
      "title",
      REFUSED_COMMAND.requested_by,
    ); // le compte d'un autre : identifiant abrégé, entier en infobulle
  });

  it("charge les commandes plus anciennes avec le curseur de la page suivante", async () => {
    const server = serve([SIGNAL]);
    server.commands
      .mockImplementationOnce(() => json({ items: [COMMAND], next_cursor: "curseur-2" }))
      .mockImplementationOnce(() => json({ items: [REFUSED_COMMAND], next_cursor: null }));
    render(withRole("viewer", <Signals />));
    await screen.findByRole("table");
    await userEvent.click(
      screen.getByRole("button", { name: "Afficher les commandes plus anciennes" }),
    );
    await waitFor(() =>
      expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(3),
    );
    const request = server.commands.mock.calls[1][0] as Request;
    expect(new URL(request.url).searchParams.get("cursor")).toBe("curseur-2");
    expect(
      screen.queryByRole("button", { name: "Afficher les commandes plus anciennes" }),
    ).toBeNull();
  });

  it("dit qu'un carrefour n'a reçu aucune commande", async () => {
    serve([SIGNAL], []);
    render(withRole("viewer", <Signals />));
    expect(await screen.findByText("Aucune commande pour ce carrefour.")).toBeInTheDocument();
  });

  it("choisir un autre carrefour relit son historique et cible sa commande", async () => {
    const server = serve();
    render(withRole("operator", <Signals />));
    await screen.findByRole("table");
    await userEvent.click(
      within(screen.getByRole("article", { name: "INT_02" })).getByRole("button", {
        name: "Choisir ce carrefour",
      }),
    );
    expect(
      await screen.findByRole("form", { name: "Commande manuelle — INT_02" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(server.calls).toContain("GET /api/v1/signals/INT_02/commands"));
  });
});
