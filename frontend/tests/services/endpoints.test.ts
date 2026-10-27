import { afterEach, describe, expect, it, vi } from "vitest";
import * as alerte from "@/services/alerte";
import * as apiMetier from "@/services/apiMetier";
import * as reponse from "@/services/reponse";
import * as traitement from "@/services/traitement";

type Appel = {
  nom: string;
  appel: () => Promise<unknown>;
  methode: "GET" | "POST" | "PATCH";
  chemin: string;
  corps?: unknown;
};

// Un appel de chaque opération du contrat que le tableau de bord utilise (hors sonde et flux SSE).
const appels: Appel[] = [
  {
    nom: "login",
    appel: () => apiMetier.login({ username: "ada", password: "secret" }),
    methode: "POST",
    chemin: "/api/v1/auth/login",
    corps: { username: "ada", password: "secret" },
  },
  {
    nom: "getCurrentUser",
    appel: () => apiMetier.getCurrentUser(),
    methode: "GET",
    chemin: "/api/v1/auth/me",
  },
  {
    nom: "listUsers",
    appel: () => apiMetier.listUsers({ limit: 5 }),
    methode: "GET",
    chemin: "/api/v1/users?limit=5",
  },
  {
    nom: "getUser",
    appel: () => apiMetier.getUser("u-1"),
    methode: "GET",
    chemin: "/api/v1/users/u-1",
  },
  {
    nom: "listIntersections",
    appel: () => traitement.listIntersections(),
    methode: "GET",
    chemin: "/api/v1/intersections",
  },
  {
    nom: "getIntersection",
    appel: () => traitement.getIntersection("INT_01"),
    methode: "GET",
    chemin: "/api/v1/intersections/INT_01",
  },
  {
    nom: "listRoadSegments",
    appel: () => traitement.listRoadSegments({ intersection_id: "INT_01" }),
    methode: "GET",
    chemin: "/api/v1/road-segments?intersection_id=INT_01",
  },
  {
    nom: "listIndicators",
    appel: () => traitement.listIndicators({ congestion_state: "CONGESTED", limit: 10 }),
    methode: "GET",
    chemin: "/api/v1/indicators?congestion_state=CONGESTED&limit=10",
  },
  {
    nom: "listLatestIndicators",
    appel: () => traitement.listLatestIndicators(),
    methode: "GET",
    chemin: "/api/v1/indicators/latest",
  },
  {
    nom: "getIndicator",
    appel: () => traitement.getIndicator("run:ROAD_001:60:1"),
    methode: "GET",
    chemin: "/api/v1/indicators/run%3AROAD_001%3A60%3A1",
  },
  {
    nom: "listAlerts",
    appel: () => alerte.listAlerts({ limit: 20 }),
    methode: "GET",
    chemin: "/api/v1/alerts?limit=20",
  },
  {
    nom: "getAlert",
    appel: () => alerte.getAlert("a-1"),
    methode: "GET",
    chemin: "/api/v1/alerts/a-1",
  },
  {
    nom: "acknowledgeAlert",
    appel: () => alerte.acknowledgeAlert("a-1"),
    methode: "POST",
    chemin: "/api/v1/alerts/a-1/acknowledge",
  },
  {
    nom: "listAlertRules",
    appel: () => alerte.listAlertRules(),
    methode: "GET",
    chemin: "/api/v1/alert-rules",
  },
  {
    nom: "listSignals",
    appel: () => reponse.listSignals(),
    methode: "GET",
    chemin: "/api/v1/signals",
  },
  {
    nom: "getSignal",
    appel: () => reponse.getSignal("INT_01"),
    methode: "GET",
    chemin: "/api/v1/signals/INT_01",
  },
  {
    nom: "listSignalCommands",
    appel: () => reponse.listSignalCommands("INT_01", { limit: 3 }),
    methode: "GET",
    chemin: "/api/v1/signals/INT_01/commands?limit=3",
  },
];

describe("appels centralisés dans services/", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each(appels)("$nom : $methode $chemin", async ({ appel, methode, chemin, corps }) => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => new Response("{}", { status: 200 }));
    await appel();
    const request = spy.mock.calls[0][0] as Request;
    const url = new URL(request.url);
    expect(request.method).toBe(methode);
    expect(url.pathname + url.search).toBe(chemin);
    if (corps !== undefined) expect(await request.json()).toEqual(corps);
  });

  it("transmet le corps JSON des opérations d'écriture", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => new Response("{}", { status: 200 }));
    await alerte.resolveAlert("a-1", { comment: "Résolue à la main" });
    await alerte.updateAlertRule("RULE_01", { enabled: false });
    const [resolve, rule] = spy.mock.calls.map(([request]) => request as Request);
    expect(resolve.method).toBe("POST");
    expect(new URL(resolve.url).pathname).toBe("/api/v1/alerts/a-1/resolve");
    expect(await resolve.json()).toEqual({ comment: "Résolue à la main" });
    expect(rule.method).toBe("PATCH");
    expect(new URL(rule.url).pathname).toBe("/api/v1/alert-rules/RULE_01");
    expect(await rule.json()).toEqual({ enabled: false });
  });
});
