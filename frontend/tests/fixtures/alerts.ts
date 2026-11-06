import type { Alert } from "@/services/alerte";

/** Une alerte de congestion créée, d'après le schéma `Alert` du contrat (types générés). */
export const ALERT: Alert = {
  alert_id: "3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d10",
  rule_id: "congestion.persistante",
  kind: "CONGESTION",
  state: "CREATED",
  severity: "WARNING",
  cause: "UNKNOWN",
  road_segment_id: "ROAD_001",
  intersection_id: "INT_01",
  episode_id: null,
  opened_at: "2026-10-20T08:01:00Z",
  notified_at: null,
  acknowledged_at: null,
  acknowledged_by: null,
  resolved_at: null,
  resolution: null,
  provenance: { source_type: "SIMULATED", run_id: "run-demo", scenario_id: "demo", seed: 42 },
};

/** Le message SSE d'un changement d'état, tel que le serveur l'écrit (`event`, `id`, `data`). */
export function sseMessage(changes: Partial<Alert> = {}, id = "alerte-x-created"): string {
  return `event: alert.state_changed\nid: ${id}\ndata: ${JSON.stringify({ ...ALERT, ...changes })}\n\n`;
}

/** Un corps de réponse SSE que le test alimente et termine à la main. */
export function controlledStream() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    end: () => controller.close(),
    fail: (reason: Error) => controller.error(reason),
  };
}
