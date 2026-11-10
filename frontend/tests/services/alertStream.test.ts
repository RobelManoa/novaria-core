import { afterEach, describe, expect, it, vi } from "vitest";
import type { Alert } from "@/services/alerte";
import { isAlert, openAlertStream, parseSse, type StreamStatus } from "@/services/alertStream";
import { getAccessToken, setAccessToken } from "@/services/session";
import { ALERT, controlledStream, sseMessage } from "../fixtures/alerts";

const message = sseMessage;

/** Comme `controlledStream`, mais le flux se coupe si le signal de la requête est levé. */
function abortable(signal?: AbortSignal | null) {
  const stream = controlledStream();
  signal?.addEventListener("abort", () => stream.fail(new DOMException("coupé", "AbortError")));
  return stream;
}

function recorder() {
  const statuses: StreamStatus[] = [];
  const alerts: Alert[] = [];
  const lives: number[] = [];
  return {
    statuses,
    alerts,
    lives,
    handlers: {
      onAlert: (alert: Alert) => alerts.push(alert),
      onStatus: (status: StreamStatus) => statuses.push(status),
      onLive: () => lives.push(Date.now()),
    },
  };
}

describe("parseSse : découpe d'un flux d'événements serveur", () => {
  it("rend les messages complets, avec leur événement et leur identifiant", () => {
    const { messages, rest } = parseSse(
      'event: alert.state_changed\nid: e1\ndata: {"a":1}\n\nevent: heartbeat\ndata: {}\n\n',
    );
    expect(messages).toEqual([
      { event: "alert.state_changed", id: "e1", data: '{"a":1}' },
      { event: "heartbeat", id: null, data: "{}" },
    ]);
    expect(rest).toBe("");
  });

  it("garde le message incomplet pour la suite", () => {
    const first = parseSse("event: heartbeat\ndata: {}\n\nevent: alert.state_ch");
    expect(first.messages).toHaveLength(1);
    expect(first.rest).toBe("event: alert.state_ch");
    const second = parseSse(`${first.rest}anged\ndata: {"b":2}\n\n`);
    expect(second.messages).toEqual([{ event: "alert.state_changed", id: null, data: '{"b":2}' }]);
  });

  it("ignore les commentaires, la consigne retry et les blocs sans données", () => {
    const { messages } = parseSse(": connecté\n\nretry: 3000\n\nevent: x\n\n");
    expect(messages).toEqual([]);
  });

  it("assemble un message sur plusieurs lignes data et accepte CRLF", () => {
    const { messages } = parseSse("data: a\r\ndata: b\r\n\r\n");
    expect(messages).toEqual([{ event: "message", id: null, data: "a\nb" }]);
  });

  it("lit un champ sans deux-points et retire un seul espace après les deux-points", () => {
    const { messages } = parseSse("data\n\ndata:  deux espaces\n\n");
    expect(messages).toEqual([
      { event: "message", id: null, data: "" },
      { event: "message", id: null, data: " deux espaces" },
    ]);
  });
});

describe("isAlert : forme minimale d'une alerte", () => {
  it("accepte une alerte et refuse le reste", () => {
    expect(isAlert(ALERT)).toBe(true);
    for (const bad of [
      null,
      "texte",
      42,
      {},
      { ...ALERT, state: "BIZARRE" },
      { ...ALERT, alert_id: 7 },
      { ...ALERT, opened_at: undefined },
      { ...ALERT, road_segment_id: null },
    ]) {
      expect(isAlert(bad)).toBe(false);
    }
  });
});

describe("openAlertStream : le flux en direct", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    setAccessToken(null);
  });

  it("s'ouvre avec le jeton, passe en direct, signale la connexion et livre les alertes", async () => {
    setAccessToken("jeton-d-essai");
    const stream = controlledStream();
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(stream.response);
    const { statuses, alerts, lives, handlers } = recorder();
    const close = openAlertStream(handlers);

    await vi.waitFor(() => expect(statuses).toEqual(["connecting", "live"]));
    expect(lives).toHaveLength(1);
    const request = spy.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/v1/events/stream");
    expect(request.headers.get("Authorization")).toBe("Bearer jeton-d-essai");
    expect(request.headers.get("Accept")).toBe("text/event-stream");

    stream.push(": connecté\n\n");
    stream.push(message());
    stream.push(message({ state: "NOTIFIED" }, "alerte-x-notified"));
    await vi.waitFor(() => expect(alerts.map((a) => a.state)).toEqual(["CREATED", "NOTIFIED"]));
    close();
  });

  it("reconstitue un message coupé entre deux morceaux", async () => {
    setAccessToken("jeton");
    const stream = controlledStream();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(stream.response);
    const { alerts, handlers } = recorder();
    const close = openAlertStream(handlers);
    const text = message();
    stream.push(text.slice(0, 40));
    stream.push(text.slice(40));
    await vi.waitFor(() => expect(alerts).toHaveLength(1));
    close();
  });

  it("ignore un battement de cœur, un autre type d'événement et un message illisible", async () => {
    setAccessToken("jeton");
    const stream = controlledStream();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(stream.response);
    const { alerts, handlers } = recorder();
    const close = openAlertStream(handlers);
    stream.push('event: heartbeat\ndata: {"time":"2026-10-20T08:00:00Z"}\n\n');
    stream.push("event: signal.status\ndata: {}\n\n");
    stream.push("event: alert.state_changed\ndata: pas du json\n\n");
    stream.push('event: alert.state_changed\ndata: {"state":"CREATED"}\n\n'); // pas une alerte
    stream.push(message());
    await vi.waitFor(() => expect(alerts).toHaveLength(1));
    close();
  });

  it("se reconnecte après une fin de flux, et signale chaque connexion pour relire la liste", async () => {
    setAccessToken("jeton");
    const first = controlledStream();
    const second = controlledStream();
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(first.response)
      .mockResolvedValueOnce(second.response);
    const { statuses, alerts, lives, handlers } = recorder();
    const close = openAlertStream(handlers, { retryMs: 5 });
    await vi.waitFor(() => expect(lives).toHaveLength(1));
    first.end();
    await vi.waitFor(() => expect(lives).toHaveLength(2));
    expect(statuses).toEqual(["connecting", "live", "offline", "connecting", "live"]);
    second.push(message({ alert_id: "autre" }));
    await vi.waitFor(() => expect(alerts).toHaveLength(1));
    expect(spy).toHaveBeenCalledTimes(2);
    close();
  });

  it("retente après une erreur du serveur, avec un délai qui double", async () => {
    setAccessToken("jeton");
    const stream = controlledStream();
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("indisponible", { status: 503 }))
      .mockRejectedValueOnce(new TypeError("réseau coupé"))
      .mockResolvedValueOnce(stream.response);
    const { statuses, lives, handlers } = recorder();
    const close = openAlertStream(handlers, { retryMs: 5, maxRetryMs: 20 });
    await vi.waitFor(() => expect(lives).toHaveLength(1), { timeout: 2000 });
    expect(spy).toHaveBeenCalledTimes(3);
    expect(statuses.filter((s) => s === "offline")).toHaveLength(2);
    close();
  });

  it("tient la connexion pour morte après un silence trop long et se reconnecte", async () => {
    setAccessToken("jeton");
    const silent = vi.fn();
    const next = controlledStream();
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      silent();
      if (silent.mock.calls.length > 1) return next.response;
      return abortable(init?.signal).response;
    });
    const { statuses, lives, handlers } = recorder();
    const close = openAlertStream(handlers, { retryMs: 5, staleMs: 30 });
    await vi.waitFor(() => expect(lives).toHaveLength(2), { timeout: 2000 });
    expect(spy).toHaveBeenCalledTimes(2);
    expect(statuses).toContain("offline");
    close();
  });

  it("un jeton refusé ferme la session et n'est pas retenté", async () => {
    setAccessToken("jeton-expire");
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));
    const { statuses, handlers } = recorder();
    openAlertStream(handlers, { retryMs: 5 });
    await vi.waitFor(() => expect(statuses).toEqual(["connecting", "offline"]));
    expect(getAccessToken()).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("un rôle refusé n'est pas retenté et ne ferme pas la session", async () => {
    setAccessToken("jeton");
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 403 }));
    const { statuses, handlers } = recorder();
    openAlertStream(handlers, { retryMs: 5 });
    await vi.waitFor(() => expect(statuses).toEqual(["connecting", "offline"]));
    expect(getAccessToken()).toBe("jeton");
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("sans jeton, il ne contacte pas le serveur", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    const { statuses, handlers } = recorder();
    openAlertStream(handlers);
    await vi.waitFor(() => expect(statuses).toEqual(["connecting", "offline"]));
    expect(spy).not.toHaveBeenCalled();
  });

  it("une réponse sans corps est une erreur à retenter", async () => {
    setAccessToken("jeton");
    const stream = controlledStream();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(stream.response);
    const { lives, handlers } = recorder();
    const close = openAlertStream(handlers, { retryMs: 5 });
    await vi.waitFor(() => expect(lives).toHaveLength(1), { timeout: 2000 });
    close();
  });

  it("l'arrêt coupe la connexion, réveille l'attente et ne livre plus rien", async () => {
    setAccessToken("jeton");
    const stream = controlledStream();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      init?.signal?.addEventListener("abort", () => stream.end());
      return stream.response;
    });
    const { statuses, alerts, handlers } = recorder();
    const close = openAlertStream(handlers, { retryMs: 60_000 });
    await vi.waitFor(() => expect(statuses).toContain("live"));
    close();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(alerts).toEqual([]);
    expect(statuses.at(-1)).toBe("live"); // aucun « offline » après un arrêt voulu
  });

  it("l'arrêt pendant l'attente d'une reconnexion la réveille", async () => {
    setAccessToken("jeton");
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 503 }));
    const { statuses, handlers } = recorder();
    const close = openAlertStream(handlers, { retryMs: 60_000 });
    await vi.waitFor(() => expect(statuses).toContain("offline"));
    close(); // sans réveil, la boucle attendrait une minute
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(statuses).toEqual(["connecting", "offline"]);
  });
});
