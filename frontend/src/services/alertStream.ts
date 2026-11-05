import type { Alert } from "./alerte";
import { clearSession, getAccessToken } from "./session";

// Flux d'événements en direct du service d'alerte : `GET /api/v1/events/stream` (SSE, MS-11).
//
// Pourquoi `fetch` et pas `EventSource` : `EventSource` ne permet pas de poser l'en-tête `Authorization`,
// et le jeton ne doit pas voyager dans l'adresse (journaux des serveurs). Ce module lit donc le corps de
// la réponse en continu et découpe lui-même les messages (`parseSse`).
//
// Il reconnecte tout seul : coupure réseau, redémarrage du service, ou silence trop long (le serveur
// envoie un battement toutes les 30 s ; au-delà de `staleMs` sans un octet, la connexion est tenue pour
// morte). Chaque connexion réussie est signalée (`onLive`) pour que l'appelant relise la liste : les
// événements émis pendant une coupure ne sont pas rejoués.

export type StreamStatus = "connecting" | "live" | "offline";

export interface SseMessage {
  event: string;
  id: string | null;
  data: string;
}

/**
 * Découpe un flux SSE : les messages complets (terminés par une ligne vide) et le reste, à rejouer avec
 * la suite. Les commentaires (`: ...`) et les lignes `retry:` ne produisent pas de message.
 */
export function parseSse(text: string): { messages: SseMessage[]; rest: string } {
  const blocks = text.replaceAll("\r\n", "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  const messages: SseMessage[] = [];
  for (const block of blocks) {
    let event = "message";
    let id: string | null = null;
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line === "" || line.startsWith(":")) continue;
      const separator = line.indexOf(":");
      const field = separator < 0 ? line : line.slice(0, separator);
      const value = separator < 0 ? "" : line.slice(separator + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "id") id = value;
      else if (field === "data") data.push(value);
    }
    if (data.length > 0) messages.push({ event, id, data: data.join("\n") });
  }
  return { messages, rest };
}

const STATES = new Set(["CREATED", "NOTIFIED", "ACKNOWLEDGED", "RESOLVED"]);

/** Vrai si `value` a la forme minimale d'une alerte : de quoi la ranger, jamais de quoi la croire. */
export function isAlert(value: unknown): value is Alert {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.alert_id === "string" &&
    typeof candidate.state === "string" &&
    STATES.has(candidate.state) &&
    typeof candidate.opened_at === "string" &&
    typeof candidate.road_segment_id === "string"
  );
}

export interface AlertStreamHandlers {
  /** Une alerte vient de changer d'état. */
  onAlert: (alert: Alert) => void;
  onStatus: (status: StreamStatus) => void;
  /** La connexion est ouverte : le moment de relire la liste des alertes. */
  onLive?: () => void;
}

export interface AlertStreamOptions {
  /** Premier délai avant une reconnexion ; il double à chaque échec, jusqu'à `maxRetryMs`. */
  retryMs?: number;
  maxRetryMs?: number;
  /** Silence au-delà duquel la connexion est tenue pour morte. */
  staleMs?: number;
}

/** Comme `client.ts` : l'origine de la page, car un `Request` exige une URL absolue. */
const STREAM_URL = `${globalThis.location?.origin ?? ""}/api/v1/events/stream`;

/** Ouvre le flux et le garde ouvert. Rend la fonction qui l'arrête. */
export function openAlertStream(
  handlers: AlertStreamHandlers,
  { retryMs = 2000, maxRetryMs = 30_000, staleMs = 75_000 }: AlertStreamOptions = {},
): () => void {
  let stopped = false;
  let failures = 0;
  let controller: AbortController | null = null;
  let wake: (() => void) | null = null;

  function wait(milliseconds: number): Promise<void> {
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, milliseconds);
      wake = () => {
        clearTimeout(timer);
        resolve();
      };
    });
  }

  /** Lit une connexion jusqu'à sa fin ; rend faux si le service refuse le jeton (inutile de réessayer). */
  async function readOnce(): Promise<boolean> {
    const token = getAccessToken();
    if (!token) return false;
    controller = new AbortController();
    const current = controller;
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    const rearm = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(() => current.abort(), staleMs);
    };
    try {
      rearm();
      const request = new Request(STREAM_URL, {
        headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
        cache: "no-store",
      });
      // Le signal passe par le second argument : c'est ce qui annule la lecture en cours (arrêt, silence).
      const response = await globalThis.fetch(request, { signal: current.signal });
      if (response.status === 401 || response.status === 403) {
        if (response.status === 401) clearSession();
        return false;
      }
      if (!response.ok || !response.body) return true;
      handlers.onStatus("live");
      handlers.onLive?.();
      failures = 0;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        rearm();
        const parsed = parseSse(buffer + decoder.decode(value, { stream: true }));
        buffer = parsed.rest;
        for (const message of parsed.messages) dispatch(message);
      }
    } catch {
      // Coupure, silence trop long ou arrêt demandé : la boucle décide de la suite.
    } finally {
      clearTimeout(watchdog);
    }
    return true;
  }

  function dispatch(message: SseMessage): void {
    if (message.event !== "alert.state_changed") return;
    try {
      const data: unknown = JSON.parse(message.data);
      if (isAlert(data)) handlers.onAlert(data);
    } catch {
      // Un message illisible ne coupe pas le flux : il est ignoré.
    }
  }

  void (async () => {
    handlers.onStatus("connecting");
    while (!stopped) {
      const retry = await readOnce();
      if (stopped || !retry) break;
      handlers.onStatus("offline");
      failures += 1;
      await wait(Math.min(retryMs * 2 ** (failures - 1), maxRetryMs));
      if (!stopped) handlers.onStatus("connecting");
    }
    if (!stopped) handlers.onStatus("offline");
  })();

  return () => {
    stopped = true;
    controller?.abort();
    wake?.();
  };
}
