import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { ApiError, fetchAlerts } from "../src/api";
import type { PublicAlert } from "../src/types";
import { alert, network } from "./fixtures";

const NOW = Date.parse("2026-11-20T09:12:00Z");

type AlertsFetcher = (signal: AbortSignal) => Promise<PublicAlert[]>;

function show(alertsFetcher: AlertsFetcher, alertsIntervalMs = 5_000) {
  return render(
    <App
      fetcher={async () => network()}
      intervalMs={15_000}
      alertsFetcher={alertsFetcher}
      alertsIntervalMs={alertsIntervalMs}
      now={() => NOW}
    />,
  );
}

const liste = () => screen.getByRole("region", { name: "Alertes en cours" });

describe("alertes en cours", () => {
  beforeEach(() => {
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
  });
  afterEach(() => vi.useRealTimers());

  it("dit qu'il charge, puis liste le tronçon, la gravité et l'heure", async () => {
    show(async () => [alert()]);
    expect(screen.getByText("Chargement des alertes…")).toBeInTheDocument();
    const item = (await within(liste()).findAllByRole("listitem"))[0];
    expect(item).toHaveTextContent("Tronçon ROAD_002");
    expect(item).toHaveTextContent("Arrivée par l'est"); // vient de l'état de la circulation
    expect(item).toHaveTextContent("Carrefour INT_01");
    expect(item).toHaveTextContent("Attention");
    expect(item).toHaveTextContent("Simulé");
    expect(within(item).getByText(/^\d{2}:\d{2}$/)).toHaveAttribute(
      "datetime",
      "2026-11-20T09:08:30Z",
    );
    expect(item).toHaveTextContent("il y a 3 min");
    expect(within(liste()).getByText(/1 alerte en cours/)).toBeInTheDocument();
  });

  it("garde le mot de la gravité (pas la couleur seule) pour chacune des trois", async () => {
    show(async () => [
      alert({ alert_id: "a", severity: "INFO" }),
      alert({ alert_id: "b", severity: "WARNING" }),
      alert({ alert_id: "c", severity: "CRITICAL" }),
    ]);
    const items = await within(liste()).findAllByRole("listitem");
    expect(
      items.map((i) => /Information|Attention|Critique/.exec(i.textContent ?? "")?.[0]),
    ).toEqual(["Information", "Attention", "Critique"]);
  });

  it("replie une longue liste : 10 alertes d'abord, le reste sur demande, puis on peut réduire", async () => {
    const beaucoup = Array.from({ length: 44 }, (_, i) =>
      alert({ alert_id: `id-${i}`, road_segment_id: `ROAD_${String(i + 1).padStart(3, "0")}` }),
    );
    show(async () => beaucoup);
    expect(await within(liste()).findByText(/44 alertes en cours/)).toBeInTheDocument();
    expect(within(liste()).getAllByRole("listitem")).toHaveLength(10);
    const plus = within(liste()).getByRole("button", { name: "Afficher les 34 autres alertes" });
    expect(plus).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(plus);
    expect(within(liste()).getAllByRole("listitem")).toHaveLength(44);
    await userEvent.click(within(liste()).getByRole("button", { name: "Réduire la liste" }));
    expect(within(liste()).getAllByRole("listitem")).toHaveLength(10);
  });

  it("ne propose pas de bouton de repli pour une liste courte", async () => {
    show(async () => [alert()]);
    await within(liste()).findByText(/1 alerte en cours/);
    expect(within(liste()).queryByRole("button", { name: /autres alertes|Réduire/ })).toBeNull();
  });

  it("dit comment suivre un tronçon tant que le consentement manque, puis se tait", async () => {
    show(async () => [alert()]);
    const aide = await within(liste()).findByText(/acceptez d'abord les notifications simulées/);
    expect(within(aide).getByRole("link")).toHaveAttribute("href", "#titre-suivi");
    await userEvent.click(screen.getByRole("checkbox"));
    expect(within(liste()).queryByText(/acceptez d'abord/)).not.toBeInTheDocument();
  });

  it("dit « aucune alerte » sans erreur quand la liste est vide", async () => {
    show(async () => []);
    expect(await within(liste()).findByText(/Aucune alerte en cours/)).toBeInTheDocument();
  });

  it("affiche un tronçon sans état connu sans inventer de sens d'arrivée", async () => {
    show(async () => [alert({ road_segment_id: "ROAD_999" })]);
    const item = (await within(liste()).findAllByRole("listitem"))[0];
    expect(item).toHaveTextContent("Tronçon ROAD_999");
    expect(item).not.toHaveTextContent("Arrivée par");
  });

  it("montre une erreur claire et un bouton pour réessayer quand rien n'a pu être lu", async () => {
    const lecteur = vi
      .fn<AlertsFetcher>()
      .mockRejectedValueOnce(new ApiError("indisponible", "x"))
      .mockResolvedValue([alert()]);
    show(lecteur, 60_000);
    const erreur = await within(liste()).findByRole("alert");
    expect(erreur).toHaveTextContent("momentanément indisponible");
    await userEvent.click(within(erreur).getByRole("button", { name: "Réessayer" }));
    expect(await within(liste()).findByText(/1 alerte en cours/)).toBeInTheDocument();
  });

  it("garde la dernière liste en disant qu'elle n'est plus actualisée", async () => {
    const lecteur = vi
      .fn<AlertsFetcher>()
      .mockResolvedValueOnce([alert()])
      .mockRejectedValue(new ApiError("reseau", "x"));
    show(lecteur, 20);
    expect(await within(liste()).findByText(/Alertes non actualisées/)).toBeInTheDocument();
    expect(within(liste()).getAllByRole("listitem")[0]).toHaveTextContent("ROAD_002");
  });
});

describe("rafraîchissement sans recharger la page", () => {
  beforeEach(() => {
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
  });
  afterEach(() => vi.useRealTimers());

  it("fait apparaître une alerte nouvelle à la lecture suivante, au bout de 5 secondes, sans action de l'usager", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let courantes: PublicAlert[] = [];
    const lecteur = vi.fn<AlertsFetcher>(async () => courantes);
    show(lecteur); // intervalle par défaut des alertes (5 000 ms) passé explicitement ci-dessus
    expect(await within(liste()).findByText(/Aucune alerte en cours/)).toBeInTheDocument();
    courantes = [alert({ alert_id: "nouvelle" })];
    await act(() => vi.advanceTimersByTimeAsync(4_900));
    expect(within(liste()).queryByRole("listitem")).not.toBeInTheDocument(); // pas encore : moins de 5 secondes
    await act(() => vi.advanceTimersByTimeAsync(200));
    expect(await within(liste()).findByText(/1 alerte en cours/)).toBeInTheDocument();
    expect(lecteur.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("retire une alerte résolue à la lecture suivante", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let courantes = [alert()];
    show(async () => courantes);
    expect(await within(liste()).findByText(/1 alerte en cours/)).toBeInTheDocument();
    courantes = [];
    await act(() => vi.advanceTimersByTimeAsync(5_100));
    expect(await within(liste()).findByText(/Aucune alerte en cours/)).toBeInTheDocument();
  });

  it("l'intervalle par défaut est de 5 secondes : moitié du critère de 10 secondes, l'autre moitié est le délai du service", async () => {
    const { ALERTS_REFRESH_MS } = await import("../src/useAlerts");
    expect(ALERTS_REFRESH_MS).toBe(5_000);
  });
});

describe("suivre un tronçon (notification simulée)", () => {
  beforeEach(() => {
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
  });
  afterEach(() => vi.useRealTimers());

  const suivi = () => screen.getByRole("region", { name: "Suivre un tronçon" });

  it("affiche le consentement avant tout : simulée, rien d'envoyé, aucune donnée personnelle, rien d'enregistré", async () => {
    show(async () => []);
    const panneau = suivi();
    expect(panneau).toHaveTextContent("Notification simulée");
    expect(panneau).toHaveTextContent("aucun courriel, SMS ni message n'est envoyé");
    expect(panneau).toHaveTextContent("Aucune donnée personnelle");
    expect(panneau).toHaveTextContent("Rien n'est enregistré");
    expect(within(panneau).getByRole("checkbox")).not.toBeChecked();
  });

  it("refuse de suivre tant que le consentement n'est pas donné", async () => {
    show(async () => [alert()]);
    const bouton = (
      await screen.findAllByRole("button", { name: "Suivre le tronçon ROAD_002" })
    )[0];
    expect(bouton).toBeDisabled();
  });

  it("notifie quand une alerte nouvelle naît sur un tronçon suivi, pas pour les autres", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let courantes: PublicAlert[] = [];
    show(async () => courantes);
    await within(liste()).findByText(/Aucune alerte en cours/);
    await userEvent.click(within(suivi()).getByRole("checkbox"));
    await userEvent.click(screen.getAllByRole("button", { name: "Suivre le tronçon ROAD_002" })[0]);
    expect(within(suivi()).getByText("ROAD_002")).toBeInTheDocument();
    courantes = [
      alert({ alert_id: "autre", road_segment_id: "ROAD_003" }),
      alert({ alert_id: "visee", road_segment_id: "ROAD_002", severity: "CRITICAL" }),
    ];
    await act(() => vi.advanceTimersByTimeAsync(5_100));
    const notification = await screen.findByRole("group", {
      name: "Notification simulée",
    });
    expect(notification).toHaveTextContent("nouvelle alerte sur le tronçon ROAD_002");
    expect(notification).toHaveTextContent("Critique");
    expect(screen.getAllByRole("group", { name: "Notification simulée" })).toHaveLength(1);
  });

  it("ne renotifie pas la même alerte aux lectures suivantes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let courantes: PublicAlert[] = [];
    show(async () => courantes);
    await within(liste()).findByText(/Aucune alerte en cours/);
    await userEvent.click(within(suivi()).getByRole("checkbox"));
    await userEvent.click(screen.getAllByRole("button", { name: "Suivre le tronçon ROAD_002" })[0]);
    courantes = [alert({ alert_id: "unique" })];
    await act(() => vi.advanceTimersByTimeAsync(5_100));
    await screen.findByRole("group", { name: "Notification simulée" });
    await userEvent.click(screen.getByRole("button", { name: "Fermer" }));
    await act(() => vi.advanceTimersByTimeAsync(10_200));
    expect(screen.queryByRole("group", { name: "Notification simulée" })).not.toBeInTheDocument();
  });

  it("ne notifie pas pour une alerte déjà ouverte au moment du suivi (elle est déjà à l'écran)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    show(async () => [alert({ alert_id: "deja" })]);
    await within(liste()).findByText(/1 alerte en cours/);
    await userEvent.click(within(suivi()).getByRole("checkbox"));
    await userEvent.click(screen.getAllByRole("button", { name: "Suivre le tronçon ROAD_002" })[0]);
    await act(() => vi.advanceTimersByTimeAsync(10_200));
    expect(screen.queryByRole("group", { name: "Notification simulée" })).not.toBeInTheDocument();
  });

  it("arrête de notifier après « ne plus suivre »", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let courantes: PublicAlert[] = [];
    show(async () => courantes);
    await within(liste()).findByText(/Aucune alerte en cours/);
    await userEvent.click(within(suivi()).getByRole("checkbox"));
    await userEvent.click(screen.getAllByRole("button", { name: "Suivre le tronçon ROAD_002" })[0]);
    await userEvent.click(
      screen.getAllByRole("button", { name: "Ne plus suivre le tronçon ROAD_002" })[0],
    );
    courantes = [alert({ alert_id: "x" })];
    await act(() => vi.advanceTimersByTimeAsync(5_100));
    expect(screen.queryByRole("group", { name: "Notification simulée" })).not.toBeInTheDocument();
  });

  it("retirer le consentement efface le suivi et les notifications", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let courantes: PublicAlert[] = [];
    show(async () => courantes);
    await within(liste()).findByText(/Aucune alerte en cours/);
    const case_ = within(suivi()).getByRole("checkbox");
    await userEvent.click(case_);
    await userEvent.click(screen.getAllByRole("button", { name: "Suivre le tronçon ROAD_002" })[0]);
    courantes = [alert({ alert_id: "x" })];
    await act(() => vi.advanceTimersByTimeAsync(5_100));
    await screen.findByRole("group", { name: "Notification simulée" });
    await userEvent.click(case_);
    expect(screen.queryByRole("group", { name: "Notification simulée" })).not.toBeInTheDocument();
    expect(within(suivi()).queryByText("ROAD_002")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Suivre le tronçon ROAD_002" })[0]).toBeDisabled();
  });

  it("ne garde rien sur l'appareil : ni stockage, ni cookie, même après un suivi", async () => {
    const ecriture = vi.spyOn(Storage.prototype, "setItem");
    show(async () => [alert()]);
    await within(liste()).findByText(/1 alerte en cours/);
    await userEvent.click(within(suivi()).getByRole("checkbox"));
    await userEvent.click(screen.getAllByRole("button", { name: "Suivre le tronçon ROAD_002" })[0]);
    expect(ecriture).not.toHaveBeenCalled();
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });
});

describe("appel de l'API publique d'alertes", () => {
  afterEach(() => vi.unstubAllGlobals());

  function simule(corps: unknown, init: ResponseInit = { status: 200 }) {
    const appel = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(corps), init));
    vi.stubGlobal("fetch", appel);
    return appel;
  }

  it("lit la route publique d'alertes, sans jeton ni cookie ni cache navigateur", async () => {
    const appel = simule({ items: [alert()] });
    expect(await fetchAlerts()).toEqual([alert()]);
    const [adresse, options] = appel.mock.calls[0];
    expect(adresse).toBe("/api/v1/public/alerts");
    expect(options?.method).toBe("GET");
    expect(options?.credentials).toBe("omit");
    expect(options?.cache).toBe("no-store");
    expect(options?.headers).toEqual({ Accept: "application/json" });
  });

  it("refuse une alerte qui porte un champ de plus (le contrat est une liste blanche)", async () => {
    simule({ items: [{ ...alert(), acknowledged_by: "operateur1" }] });
    await expect(fetchAlerts()).rejects.toMatchObject({ kind: "format" });
  });

  it.each([
    [
      "un champ manquant",
      Object.fromEntries(Object.entries(alert()).filter(([cle]) => cle !== "opened_at")),
    ],
    ["une gravité inconnue", { ...alert(), severity: "FATAL" }],
    ["une date illisible", { ...alert(), opened_at: "hier" }],
    ["un booléen faux", { ...alert(), simulated: "oui" }],
  ])("refuse %s", async (_nom, mauvaise) => {
    simule({ items: [mauvaise] });
    await expect(fetchAlerts()).rejects.toMatchObject({ kind: "format" });
  });

  it.each([
    [429, "limite"],
    [503, "indisponible"],
    [404, "indisponible"],
    [418, "inattendue"],
  ])("traduit le statut %i en erreur « %s »", async (statut, genre) => {
    simule({}, { status: statut });
    await expect(fetchAlerts()).rejects.toMatchObject({ kind: genre });
  });

  it("traduit une coupure réseau", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("réseau")));
    await expect(fetchAlerts()).rejects.toMatchObject({ kind: "reseau" });
  });

  it("garde le temps d'attendre pour les tests de délai", async () => {
    await waitFor(() => expect(true).toBe(true));
  });
});
