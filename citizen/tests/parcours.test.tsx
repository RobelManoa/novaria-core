import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { CLE } from "../src/stockage";
import type { PublicAlert, SegmentState } from "../src/types";
import { alert, network, ouvrirDetail, retourAccueil, segment } from "./fixtures";

/**
 * Le parcours du citoyen (ADR-031), de bout en bout DANS l'application : le vrai code du réseau (`src/api.ts`) parle à un faux serveur qui
 * remplace `fetch`. Rien ne sort de la machine : toute adresse qui n'est pas l'une des deux routes publiques est refusée par le faux.
 *
 * Ouvrir → voir des trajets proposés avec leur verdict → garder le sien et se faire prévenir → une alerte s'ouvre : le message apparaît →
 * le service de circulation tombe : la dernière information reste, un message clair le dit → il revient : tout se rétablit → fermer et
 * rouvrir : le trajet est là.
 */
const PUBLIQUES = ["/api/v1/public/congestion", "/api/v1/public/alerts"];

interface Serveur {
  segments: SegmentState[];
  alertes: PublicAlert[];
  circulationEnPanne: boolean;
  appels: { url: string; init?: RequestInit }[];
  refus: string[];
}

function installerServeur(): Serveur {
  const serveur: Serveur = {
    segments: network(),
    alertes: [],
    circulationEnPanne: false,
    appels: [],
    refus: [],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      serveur.appels.push({ url, init });
      if (!PUBLIQUES.includes(url)) {
        serveur.refus.push(url);
        throw new TypeError("réseau extérieur interdit");
      }
      if (url.endsWith("/congestion")) {
        if (serveur.circulationEnPanne) {
          return Response.json(
            {
              type: "x",
              title: "Service indisponible",
              status: 503,
              code: "UPSTREAM_UNAVAILABLE",
              detail: "x",
              correlation_id: "c",
            },
            { status: 503 },
          );
        }
        return Response.json({ items: serveur.segments });
      }
      return Response.json({ items: serveur.alertes });
    }),
  );
  return serveur;
}

const region = () => screen.getByRole("region", { name: /trajets/i });
const avancer = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

describe("parcours du citoyen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("de l'ouverture à la panne, à la reprise et au retour le lendemain, sans réseau extérieur", async () => {
    const serveur = installerServeur();
    const premiere = render(<App />);

    // 1. Il ouvre : des trajets pour essayer, avec le verdict de chacun et la mention des données simulées.
    expect(await screen.findByRole("region", { name: /trajets/i })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Données simulées");
    const gare = within(region()).getByRole("listitem", { name: "Aller à la gare" });
    expect(gare).toHaveTextContent("Bloqué");
    expect(gare).toHaveTextContent("Prévoyez beaucoup de retard");

    // 2. Il garde ce trajet et demande à être prévenu.
    await userEvent.click(within(gare).getByRole("button", { name: "Garder ce trajet" }));
    await ouvrirDetail("Aller à la gare");
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Me prévenir si ce trajet se bloque" }),
    );
    expect(JSON.parse(window.localStorage.getItem(CLE) ?? "{}").trajets[0].prevenir).toBe(true);
    await retourAccueil();

    // 3. Le trajet se dégage, puis une alerte s'ouvre : il le voit seul, sans rien faire.
    serveur.segments = serveur.segments.map((s) =>
      s.road_segment_id === "ROAD_001" ? segment({ ...s, state: "FREE_FLOW" }) : s,
    );
    await avancer(15_100);
    expect(within(region()).getByRole("listitem", { name: "Aller à la gare" })).toHaveTextContent(
      "Libre",
    );
    expect(within(region()).getByRole("listitem", { name: "Aller à la gare" })).toHaveTextContent(
      "Vous pouvez partir.",
    );
    serveur.alertes = [alert({ alert_id: "a1", road_segment_id: "ROAD_004", severity: "WARNING" })];
    serveur.segments = serveur.segments.map((s) =>
      s.road_segment_id === "ROAD_004" ? segment({ ...s, state: "CONGESTED" }) : s,
    );
    await avancer(15_100);
    expect(screen.getByRole("group", { name: "Message pour votre trajet" })).toHaveTextContent(
      "Aller à la gare",
    );
    expect(within(region()).getByRole("listitem", { name: "Aller à la gare" })).toHaveTextContent(
      "Bloqué",
    );

    // 4. Le service de circulation tombe : la dernière information reste, un message clair le dit, rien de technique.
    serveur.circulationEnPanne = true;
    await avancer(15_100);
    expect(await screen.findByText(/Mise à jour impossible/)).toBeInTheDocument();
    expect(within(region()).getByRole("listitem", { name: "Aller à la gare" })).toHaveTextContent(
      "Bloqué",
    );
    expect(document.body.textContent).not.toMatch(/503|UPSTREAM|undefined|\[object|TypeError/);

    // 5. Il revient : le message disparaît seul.
    serveur.circulationEnPanne = false;
    await avancer(15_100);
    expect(screen.queryByText(/Mise à jour impossible/)).not.toBeInTheDocument();

    // 6. Le lendemain : il rouvre, son trajet est là, avec « Me prévenir », sans rien refaire.
    premiere.unmount();
    render(<App />);
    expect(await screen.findByRole("region", { name: /trajets/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Mes trajets");
    expect(within(region()).getByRole("listitem", { name: "Aller à la gare" })).toBeInTheDocument();
    expect(within(region()).getByRole("listitem", { name: "Aller à la gare" })).toHaveTextContent(
      "Je suis prévenu",
    );

    // Aucun réseau extérieur : seules les deux routes publiques ont été appelées, sans jeton, sans cookie, en lecture.
    expect(serveur.refus).toEqual([]);
    expect(serveur.appels.length).toBeGreaterThan(8);
    for (const { url, init } of serveur.appels) {
      expect(PUBLIQUES).toContain(url);
      expect(url.startsWith("/")).toBe(true);
      expect(init?.method).toBe("GET");
      expect(init?.credentials).toBe("omit");
      expect(init?.headers).toEqual({ Accept: "application/json" });
    }
    expect(document.cookie).toBe("");
  });

  it("refuse toute adresse extérieure : le garde du faux serveur fonctionne", async () => {
    const serveur = installerServeur();
    await expect(fetch("https://exemple.org/donnees")).rejects.toThrow(TypeError);
    await expect(fetch("http://127.0.0.1:8000/api/v1/public/alerts")).rejects.toThrow(TypeError);
    expect(serveur.refus).toHaveLength(2);
  });

  it("à l'ouverture pendant la panne, un message clair et « Réessayer », puis les trajets quand le service revient", async () => {
    const serveur = installerServeur();
    serveur.circulationEnPanne = true;
    render(<App />);
    const erreur = await screen.findByRole("alert");
    expect(erreur).toHaveTextContent("momentanément indisponible");
    expect(erreur.textContent).not.toMatch(/503|UPSTREAM/);
    serveur.circulationEnPanne = false;
    await userEvent.click(within(erreur).getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByRole("region", { name: /trajets/i })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
