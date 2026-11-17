import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CommandPanel from "@/features/signals/CommandPanel";
import { setAccessToken } from "@/services/session";
import { COMMAND, SIGNAL, json, problem, withRole } from "../../fixtures/signals";

function setup(role: "viewer" | "operator" | "admin" = "operator") {
  const onSent = vi.fn();
  const bodies: unknown[] = [];
  const post = vi.fn(() => json(COMMAND, 202));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    bodies.push(await request.clone().json());
    return post();
  });
  render(withRole(role, <CommandPanel signal={SIGNAL} onSent={onSent} />));
  return { onSent, bodies, post };
}

const motif = () => screen.getByLabelText("Motif (conservé dans le journal)");
const prepare = () => userEvent.click(screen.getByRole("button", { name: "Préparer la commande" }));

describe("CommandPanel : la commande manuelle protégée par rôle", () => {
  beforeEach(() => setAccessToken("jeton-d-essai"));
  afterEach(() => {
    vi.restoreAllMocks();
    setAccessToken(null);
  });

  it.each(["operator", "admin"] as const)("le rôle %s voit le formulaire", (role) => {
    setup(role);
    expect(screen.getByRole("form", { name: "Commande manuelle — INT_01" })).toBeInTheDocument();
  });

  it("le lecteur ne voit ni formulaire ni bouton, seulement la raison", () => {
    setup("viewer");
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.getByRole("note")).toHaveTextContent(
      "La commande manuelle est réservée aux opérateurs et aux administrateurs.",
    );
  });

  it("refuse un motif trop court sans rien envoyer", async () => {
    const { post } = setup();
    await userEvent.type(motif(), "ab");
    await prepare();
    expect(screen.getByRole("alert")).toHaveTextContent("au moins 3 caractères");
    expect(post).not.toHaveBeenCalled();
  });

  it.each(["9", "91", "12.5", ""])("refuse la durée « %s » avant l'envoi", async (value) => {
    const { post } = setup();
    const duration = screen.getByLabelText(/Durée/);
    await userEvent.clear(duration);
    if (value) await userEvent.type(duration, value);
    await userEvent.type(motif(), "Évacuation");
    await prepare();
    expect(screen.getByRole("alert")).toHaveTextContent("de 10 à 90");
    expect(post).not.toHaveBeenCalled();
  });

  it("demande confirmation, puis envoie la phase, la durée et le motif, et le dit journalisé", async () => {
    const { post, onSent, bodies } = setup();
    await userEvent.selectOptions(screen.getByLabelText("Phase"), "P2");
    const duration = screen.getByLabelText(/Durée/);
    await userEvent.clear(duration);
    await userEvent.type(duration, "45");
    await userEvent.type(motif(), "  Évacuation après incident confirmé ");
    await prepare();

    expect(screen.getByRole("group", { name: "Confirmation" })).toHaveTextContent(
      "Imposer la phase P2 pendant 45 s sur INT_01 ?",
    );
    expect(post).not.toHaveBeenCalled(); // rien n'est envoyé avant la confirmation
    await userEvent.click(screen.getByRole("button", { name: "Confirmer la commande" }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(bodies[0]).toEqual({
      action: "SET_PHASE",
      phase_id: "P2",
      duration_s: 45,
      reason: "Évacuation après incident confirmé",
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      `Commande appliquée et journalisée (${COMMAND.command_id}).`,
    );
    expect(onSent).toHaveBeenCalledTimes(1);
    expect(motif()).toHaveValue(""); // le motif d'une commande ne sert pas à la suivante
  });

  it("annuler la confirmation n'envoie rien", async () => {
    const { post } = setup();
    await userEvent.type(motif(), "Essai");
    await prepare();
    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));
    expect(screen.queryByRole("group", { name: "Confirmation" })).toBeNull();
    expect(post).not.toHaveBeenCalled();
  });

  it("« Rendre la main » n'envoie ni phase ni durée", async () => {
    const { bodies, post } = setup();
    await userEvent.click(screen.getByRole("radio", { name: "Rendre la main" }));
    expect(screen.queryByLabelText("Phase")).toBeNull();
    await userEvent.type(motif(), "Fin de l'incident");
    await prepare();
    await userEvent.click(screen.getByRole("button", { name: "Confirmer la commande" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(bodies[0]).toEqual({ action: "RESUME_AUTOMATIC", reason: "Fin de l'incident" });
  });

  it("modifier le formulaire après la préparation retire la confirmation", async () => {
    setup();
    await userEvent.type(motif(), "Essai");
    await prepare();
    await userEvent.type(motif(), "s");
    expect(screen.queryByRole("group", { name: "Confirmation" })).toBeNull();
  });

  it("dit le refus des garde-fous, avec ses motifs, et précise qu'il est journalisé", async () => {
    const { post, onSent } = setup();
    post.mockImplementation(() =>
      problem(422, "UNSAFE_COMMAND", {
        errors: [{ field: "duration_s", message: "PHASE_TOO_LONG" }],
      }),
    );
    await userEvent.type(motif(), "Essai");
    await prepare();
    await userEvent.click(screen.getByRole("button", { name: "Confirmer la commande" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("ne respecte pas les règles de sécurité");
    expect(alert).toHaveTextContent("Durée au-dessus du maximum (90 s)");
    expect(alert).toHaveTextContent("Le refus est journalisé.");
    expect(onSent).toHaveBeenCalledTimes(1); // l'historique se relit : le refus y figure
  });

  it("nomme le refus d'une phase trop récente, avec le motif des garde-fous", async () => {
    const { post } = setup();
    post.mockImplementation(() =>
      problem(422, "UNSAFE_COMMAND", {
        errors: [{ field: "body", message: "MIN_DURATION_NOT_ELAPSED" }],
      }),
    );
    await userEvent.type(motif(), "Essai");
    await prepare();
    await userEvent.click(screen.getByRole("button", { name: "Confirmer la commande" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "La phase en cours n'a pas encore duré 10 s",
    );
  });

  it("dit qu'une commande est déjà en cours (409)", async () => {
    const { post } = setup();
    post.mockImplementation(() => problem(409, "COMMAND_IN_PROGRESS"));
    await userEvent.type(motif(), "Essai");
    await prepare();
    await userEvent.click(screen.getByRole("button", { name: "Confirmer la commande" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Une commande est déjà en cours pour ce carrefour.");
    expect(alert).not.toHaveTextContent("journalisé");
  });

  it("dit l'accès refusé (403) sans détail technique", async () => {
    const { post } = setup();
    post.mockImplementation(() => problem(403, "FORBIDDEN"));
    await userEvent.type(motif(), "Essai");
    await prepare();
    await userEvent.click(screen.getByRole("button", { name: "Confirmer la commande" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Votre rôle ne permet pas cette action.",
    );
  });
});
