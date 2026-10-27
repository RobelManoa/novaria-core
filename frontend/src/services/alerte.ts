import type { operations, paths } from "@/types/api/alerte";
import { createApiClient, unwrap, type JsonBody, type Query } from "./client";

// Alerte usager : alertes et règles (contracts/openapi/alerte.openapi.yaml).
// Le flux `GET /api/v1/events/stream` (SSE) n'est pas un appel fetch ordinaire : il aura son propre module.
const client = createApiClient<paths>();

export async function listAlerts(query?: Query<operations["listAlerts"]>) {
  return unwrap(await client.GET("/api/v1/alerts", { params: { query } }));
}

export async function getAlert(alertId: string) {
  return unwrap(
    await client.GET("/api/v1/alerts/{alert_id}", { params: { path: { alert_id: alertId } } }),
  );
}

export async function acknowledgeAlert(alertId: string) {
  return unwrap(
    await client.POST("/api/v1/alerts/{alert_id}/acknowledge", {
      params: { path: { alert_id: alertId } },
    }),
  );
}

export async function resolveAlert(
  alertId: string,
  resolution: JsonBody<operations["resolveAlert"]>,
) {
  return unwrap(
    await client.POST("/api/v1/alerts/{alert_id}/resolve", {
      params: { path: { alert_id: alertId } },
      body: resolution,
    }),
  );
}

export async function listAlertRules() {
  return unwrap(await client.GET("/api/v1/alert-rules"));
}

export async function updateAlertRule(
  ruleId: string,
  changes: JsonBody<operations["updateAlertRule"]>,
) {
  return unwrap(
    await client.PATCH("/api/v1/alert-rules/{rule_id}", {
      params: { path: { rule_id: ruleId } },
      body: changes,
    }),
  );
}
