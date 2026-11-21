import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { ApiError } from "../src/api";
import { ecrire } from "../src/stockage";
import type { PublicAlert } from "../src/types";
import type { Trajet } from "../src/trajets";
import { alert, network, ouvrirDetail } from "./fixtures";

const NOW = Date.parse("2026-11-20T09:12:00Z");
type Alertes = (signal: AbortSignal) => Promise<PublicAlert[]>;

const gare = (prevenir: boolean): Trajet => ({
  id: "t-gare",
  nom: "Aller à la gare",
  troncons: ["ROAD_001", "ROAD_004"],
  prevenir,
});

function show(alertsFetcher: Alertes) {
  return render(
    <App
      fetcher={async () => network()}
      alertsFetcher={alertsFetcher}
      alertsIntervalMs={5_000}
      now={() => NOW}
    />,
  );
}
const messages = () => screen.queryAllByRole("group", { name: "Message pour votre trajet" });
const avancer = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
const trajets = () => screen.findByRole("region", { name: /trajets/i });

describe("« Me prévenir » (message simulé)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  it("dit en une phrase que rien n'est envoyé, sans case de consentement ni bloc juridique", async () => {
    ecrire([gare(false)]);
    show(async () => []);
    await trajets();
    const detail = await ouvrirDetail("Aller à la gare");
    expect(detail).toHaveTextContent("Rien n'est envoyé : c'est une simulation.");
    expect(screen.queryByText(/J'ai compris et j'accepte/)).not.toBeInTheDocument();
    expect(
      within(detail).getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }),
    ).not.toBeChecked();
  });

  it("prévient quand une alerte NOUVELLE s'ouvre sur un tronçon du trajet, une seule fois", async () => {
    ecrire([gare(true)]);
    let courantes: PublicAlert[] = [];
    show(async () => courantes);
    await trajets();
    await avancer(100);
    courantes = [alert({ alert_id: "a1", road_segment_id: "ROAD_004", severity: "CRITICAL" })];
    await avancer(5_100);
    const [message] = messages();
    expect(message).toHaveTextContent(
      "Votre trajet « Aller à la gare » : une alerte vient de s'ouvrir.",
    );
    expect(message).toHaveTextContent("Critique");
    expect(message).toHaveTextContent("Message simulé");
    await avancer(10_200);
    expect(messages()).toHaveLength(1);
    await userEvent.click(within(message).getByRole("button", { name: "Fermer" }));
    await avancer(10_200);
    expect(messages()).toHaveLength(0);
  });

  it("ne prévient pas pour un autre tronçon, ni quand « Me prévenir » est désactivé", async () => {
    ecrire([gare(false)]);
    let courantes: PublicAlert[] = [];
    show(async () => courantes);
    await trajets();
    await avancer(100);
    courantes = [
      alert({ alert_id: "a1", road_segment_id: "ROAD_004" }),
      alert({ alert_id: "a2", road_segment_id: "ROAD_010" }),
    ];
    await avancer(5_100);
    expect(messages()).toHaveLength(0);
    await ouvrirDetail("Aller à la gare");
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }),
    );
    courantes = [...courantes, alert({ alert_id: "a3", road_segment_id: "ROAD_010" })];
    await avancer(5_100);
    expect(messages()).toHaveLength(0); // ROAD_010 n'est pas sur ce trajet, et a1 était déjà ouverte
  });

  it("ne prévient pas pour une alerte déjà ouverte à l'ouverture de la page", async () => {
    ecrire([gare(true)]);
    show(async () => [alert({ alert_id: "deja", road_segment_id: "ROAD_001" })]);
    await trajets();
    await avancer(10_200);
    expect(messages()).toHaveLength(0);
  });

  it("l'état du trajet reste visible même quand le service des alertes tombe, et « Me prévenir » le dit", async () => {
    ecrire([gare(true)]);
    show(async () => {
      throw new ApiError("indisponible", "x");
    });
    const region = await trajets();
    expect(within(region).getByRole("listitem", { name: "Aller à la gare" })).toHaveTextContent(
      "Bloqué",
    );
    expect(await screen.findByText(/« Me prévenir » ne se met plus à jour/)).toBeInTheDocument();
    expect(
      screen.getByText(/« Me prévenir » ne se met plus à jour/).parentElement,
    ).toHaveTextContent("momentanément indisponible");
  });

  it("sans « Me prévenir », une panne du service des alertes ne dit rien : le citoyen n'a rien à en faire", async () => {
    ecrire([gare(false)]);
    show(async () => {
      throw new ApiError("indisponible", "x");
    });
    await trajets();
    await avancer(5_100);
    expect(screen.queryByText(/ne se met plus à jour/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
