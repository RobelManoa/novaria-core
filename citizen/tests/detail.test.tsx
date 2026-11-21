import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { CONSEIL, alertesDuTrajet, autresTrajets } from "../src/detail";
import { intersectionDuTroncon } from "../src/lieux";
import { TYPE_DE_ROUTE, faitsDuTroncon } from "../src/reseau";
import { lienDetail, lireRoute } from "../src/route";
import { ecrire, lire } from "../src/stockage";
import { VERDICT_PHRASE } from "../src/verdict";
import type { Trajet } from "../src/trajets";
import type { PublicAlert, SegmentState } from "../src/types";
import { alert as alerte, network } from "./fixtures";

const NOW = Date.parse("2026-11-20T09:12:00Z");

const GARE: Trajet = {
  id: "t-gare",
  nom: "Aller à la gare",
  troncons: ["ROAD_001", "ROAD_004"],
  prevenir: false,
};
const CALME: Trajet = {
  id: "t-calme",
  nom: "Rue calme",
  troncons: ["ROAD_003", "ROAD_004"],
  prevenir: false,
};
const LENT: Trajet = { id: "t-lent", nom: "Trajet lent", troncons: ["ROAD_002"], prevenir: true };

function show(options: { donnees?: SegmentState[]; alertes?: () => Promise<PublicAlert[]> } = {}) {
  return render(
    <App
      fetcher={async () => options.donnees ?? network()}
      alertsFetcher={options.alertes ?? (async () => [])}
      now={() => NOW}
    />,
  );
}

function ouvrir(trajet: Trajet) {
  window.location.hash = lienDetail(trajet.id);
}

describe("le détail d'un trajet : les règles", () => {
  it("lit l'écran demandé dans le fragment de l'adresse, et ignore tout le reste", () => {
    expect(lireRoute("#/trajet/t-gare")).toEqual({ nom: "detail", id: "t-gare" });
    expect(lireRoute("#/trajet/propose-gare-m3x9")).toEqual({
      nom: "detail",
      id: "propose-gare-m3x9",
    });
    for (const autre of ["", "#", "#/", "#/trajet/", "#/trajet/a/b", "#/trajet/<x>", "#/autre"]) {
      expect(lireRoute(autre)).toEqual({ nom: "accueil" });
    }
    expect(lireRoute(lienDetail("t-1"))).toEqual({ nom: "detail", id: "t-1" });
  });

  it("dit les faits fixes d'un endroit en mots simples, sans jamais montrer un code", () => {
    expect(faitsDuTroncon("ROAD_001")).toBe("Grand axe · 2 voies · 300 m · limité à 50 km/h");
    expect(faitsDuTroncon("ROAD_009")).toBe("Rue de liaison · 1 voie · 250 m · limité à 50 km/h");
    expect(faitsDuTroncon("ROAD_024")).toBe("Rue de quartier · 1 voie · 150 m · limité à 30 km/h");
    expect(faitsDuTroncon("ROAD_999")).toBe("");
    expect(faitsDuTroncon("n'importe quoi")).toBe("");
    expect(intersectionDuTroncon("ROAD_005")).toBe("INT_02");
    expect(intersectionDuTroncon("ROAD_999")).toBeNull();
    for (const mot of Object.values(TYPE_DE_ROUTE)) expect(mot).not.toMatch(/[A-Z]{3,}|_|\d/);
  });

  it("donne un conseil par verdict, sans durée ni heure promise", () => {
    expect(Object.keys(CONSEIL).sort()).toEqual(Object.keys(VERDICT_PHRASE).sort());
    for (const conseil of Object.values(CONSEIL)) {
      for (const texte of [conseil.maintenant, conseil.attendre ?? ""]) {
        expect(texte).not.toMatch(/\d+\s*(min|s|h)\b/i);
        expect(texte).not.toMatch(/dans \d|vers \d|d'ici/i);
      }
    }
    expect(CONSEIL.LIBRE.attendre).toBeNull();
    expect(CONSEIL.BLOQUE.attendre).toMatch(/ne pouvons pas prédire/);
  });

  it("compare avec les autres trajets, jamais avec lui-même", () => {
    const parId = new Map(network().map((s) => [s.road_segment_id, s] as const));
    expect(autresTrajets(GARE, [GARE, CALME, LENT], parId)).toEqual([
      { id: "t-calme", nom: "Rue calme", verdict: "LIBRE" },
      { id: "t-lent", nom: "Trajet lent", verdict: "RALENTI" },
    ]);
    expect(autresTrajets(GARE, [GARE], parId)).toEqual([]);
  });

  it("ne garde que les alertes des tronçons du trajet, la plus récente d'abord", () => {
    const vieille = alerte({
      alert_id: "a",
      road_segment_id: "ROAD_001",
      opened_at: "2026-11-20T09:00:00Z",
    });
    const recente = alerte({
      alert_id: "b",
      road_segment_id: "ROAD_004",
      opened_at: "2026-11-20T09:05:00Z",
    });
    const ailleurs = alerte({ alert_id: "c", road_segment_id: "ROAD_020" });
    expect(alertesDuTrajet(GARE, [vieille, ailleurs, recente]).map((a) => a.alert_id)).toEqual([
      "b",
      "a",
    ]);
    expect(alertesDuTrajet(GARE, [])).toEqual([]);
  });
});

describe("le détail d'un trajet : l'écran", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
    ecrire([GARE, CALME, LENT]);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    window.location.hash = "";
  });

  it("depuis l'accueil, la carte du trajet ouvre son détail, et « Mes trajets » revient", async () => {
    show();
    const region = await screen.findByRole("region", { name: /trajets/i });
    await userEvent.click(within(region).getByRole("link", { name: "Aller à la gare" }));
    await screen.findByRole("article", { name: "Aller à la gare" });
    expect(window.location.hash).toBe("#/trajet/t-gare");
    const titre = screen.getByRole("heading", { level: 1 });
    expect(titre).toHaveTextContent("Aller à la gare");
    expect(titre).toHaveFocus();
    expect(screen.queryByRole("region", { name: /^mes trajets$/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("link", { name: "Mes trajets" }));
    expect(await screen.findByRole("region", { name: /^mes trajets$/i })).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("un trajet bloqué : le verdict d'abord, puis les choix, la cause non confirmée et les endroits", async () => {
    ouvrir(GARE);
    show();
    const detail = await screen.findByRole("article", { name: "Aller à la gare" });

    const verdict = within(detail).getByRole("region", { name: "Verdict" });
    expect(verdict).toHaveTextContent("Bloqué");
    expect(verdict).toHaveTextContent(VERDICT_PHRASE.BLOQUE);
    expect(verdict).toHaveTextContent(/Mesure de .* \(il y a 2 min\)/);

    const decider = within(detail).getByRole("region", { name: "Partir maintenant ou attendre ?" });
    expect(decider).toHaveTextContent(CONSEIL.BLOQUE.maintenant);
    expect(decider).toHaveTextContent(CONSEIL.BLOQUE.attendre ?? "");
    expect(within(decider).getByRole("link", { name: "Trajet lent" })).toHaveAttribute(
      "href",
      "#/trajet/t-lent",
    );
    expect(decider).toHaveTextContent("Rue calme : libre");
    expect(
      within(decider).queryByRole("link", { name: "Aller à la gare" }),
    ).not.toBeInTheDocument();

    const pourquoi = within(detail).getByRole("region", { name: "Pourquoi ça bloque ?" });
    expect(pourquoi).toHaveTextContent("Cause non confirmée");
    expect(pourquoi).toHaveTextContent(/ne peuvent pas savoir si c'est un accident/);

    const ou = within(detail).getByRole("region", { name: "Où ça se passe" });
    const endroits = within(ou).getAllByRole("listitem");
    expect(endroits).toHaveLength(2);
    expect(endroits[0]).toHaveTextContent("Place de la Gare, en venant du nord");
    expect(endroits[0]).toHaveTextContent("Congestionné");
    expect(endroits[0]).toHaveTextContent("Grand axe · 2 voies · 300 m · limité à 50 km/h");
    expect(endroits[1]).toHaveTextContent("Place de la Gare, en venant de l'ouest");
    expect(endroits[1]).toHaveTextContent("Fluide");

    expect(document.body.textContent).not.toMatch(/ROAD_|INT_/);
  });

  it("un trajet libre ne propose ni d'attendre, ni de changer, ni de chercher une cause", async () => {
    ouvrir(CALME);
    show();
    const detail = await screen.findByRole("article", { name: "Rue calme" });
    expect(within(detail).getByRole("region", { name: "Verdict" })).toHaveTextContent("Libre");
    const decider = within(detail).getByRole("region", { name: "Partir maintenant ou attendre ?" });
    expect(decider).toHaveTextContent("vous pouvez partir");
    expect(within(decider).queryByText("Attendre")).not.toBeInTheDocument();
    expect(within(decider).queryByText("Changer de trajet")).not.toBeInTheDocument();
    expect(within(detail).queryByRole("region", { name: /Pourquoi/ })).not.toBeInTheDocument();
  });

  it("un trajet ralenti dit « Pourquoi ça ralentit ? »", async () => {
    ouvrir(LENT);
    show();
    const detail = await screen.findByRole("article", { name: "Trajet lent" });
    expect(within(detail).getByRole("region", { name: "Pourquoi ça ralentit ?" })).toBeVisible();
  });

  it("des mesures manquantes : « information incomplète », jamais « libre »", async () => {
    ouvrir(GARE);
    const donnees = network().map((s) =>
      s.road_segment_id === "ROAD_001" ? { ...s, state: "UNKNOWN" as const } : s,
    );
    show({ donnees });
    const detail = await screen.findByRole("article", { name: "Aller à la gare" });
    expect(within(detail).getByRole("region", { name: "Verdict" })).toHaveTextContent(
      "Information incomplète",
    );
    expect(within(detail).queryByRole("region", { name: /Pourquoi/ })).not.toBeInTheDocument();
  });

  it("montre l'alerte ouverte sur le trajet, ou dit qu'il n'y en a pas", async () => {
    ouvrir(GARE);
    const premiere = show({
      alertes: async () => [
        alerte({ road_segment_id: "ROAD_001", opened_at: "2026-11-20T09:08:30Z" }),
        alerte({ alert_id: "autre", road_segment_id: "ROAD_020" }),
      ],
    });
    let section = await screen.findByRole("region", { name: "Alerte en cours" });
    await waitFor(() => expect(within(section).getAllByRole("listitem")).toHaveLength(1));
    expect(section).toHaveTextContent("Attention");
    expect(section).toHaveTextContent(/ouverte à .* \(il y a 3 min\)/);
    premiere.unmount();

    show();
    section = await screen.findByRole("region", { name: "Alerte en cours" });
    await waitFor(() => expect(section).toHaveTextContent("Aucune alerte en cours sur ce trajet."));
  });

  it("quand le service d'alertes est en panne, il ne dit ni « oui » ni « non »", async () => {
    ouvrir(GARE);
    show({ alertes: async () => Promise.reject(new TypeError("réseau")) });
    const section = await screen.findByRole("region", { name: "Alerte en cours" });
    await waitFor(() =>
      expect(section).toHaveTextContent("Les alertes ne sont pas disponibles pour le moment."),
    );
    expect(section).not.toHaveTextContent("Aucune alerte");
  });

  it("« Me prévenir » se règle depuis le détail et reste gardé sur l'appareil", async () => {
    ouvrir(GARE);
    show();
    const detail = await screen.findByRole("article", { name: "Aller à la gare" });
    const case_ = within(detail).getByRole("checkbox", {
      name: "Me prévenir si ce trajet se bloque",
    });
    expect(case_).not.toBeChecked();
    await userEvent.click(case_);
    expect(case_).toBeChecked();
    expect(lire().trajets?.find((t) => t.id === "t-gare")?.prevenir).toBe(true);
  });

  it("supprimer le trajet depuis le détail revient à l'accueil sans lui", async () => {
    ouvrir(GARE);
    show();
    await userEvent.click(
      await screen.findByRole("button", { name: "Supprimer le trajet Aller à la gare" }),
    );
    const region = await screen.findByRole("region", { name: /^mes trajets$/i });
    expect(within(region).queryByText("Aller à la gare")).not.toBeInTheDocument();
    expect(lire().trajets?.map((t) => t.id)).toEqual(["t-calme", "t-lent"]);
    expect(window.location.hash).toBe("#/");
  });

  it("un trajet qui n'existe pas (adresse ancienne ou inventée) le dit et ramène à l'accueil", async () => {
    window.location.hash = "#/trajet/t-inconnu";
    show();
    expect(
      await screen.findByRole("heading", { level: 2, name: "Ce trajet n'existe plus" }),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("link", { name: "Retour à mes trajets" }));
    expect(await screen.findByRole("region", { name: /^mes trajets$/i })).toBeInTheDocument();
  });

  it("le bouton « retour » du navigateur ramène à l'accueil", async () => {
    ouvrir(GARE);
    show();
    await screen.findByRole("article", { name: "Aller à la gare" });
    window.location.hash = "#/";
    expect(await screen.findByRole("region", { name: /^mes trajets$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });

  it("ne demande rien de plus au réseau et n'écrit rien d'autre que les trajets", async () => {
    ouvrir(GARE);
    const fetcher = vi.fn(async () => network());
    render(<App fetcher={fetcher} alertsFetcher={async () => []} now={() => NOW} />);
    await screen.findByRole("article", { name: "Aller à la gare" });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(Object.keys(window.localStorage)).toEqual(["novaria-citoyen-trajets"]);
  });

  it("passe l'audit d'accessibilité (WCAG 2.1 AA), bloqué comme libre", async () => {
    for (const trajet of [GARE, CALME]) {
      ouvrir(trajet);
      const vue = show({ alertes: async () => [alerte({ road_segment_id: "ROAD_001" })] });
      await screen.findByRole("article", { name: trajet.nom });
      const resultat = await axe.run(document.body, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
        rules: { "color-contrast": { enabled: false } },
      });
      expect(resultat.violations.map((v) => v.id)).toEqual([]);
      vue.unmount();
    }
  });
});
