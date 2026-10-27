import type { operations, paths } from "@/types/api/reponse";
import { createApiClient, unwrap, type JsonBody, type Query } from "./client";

// Réponse extérieure : état des feux et commande manuelle (contracts/openapi/reponse.openapi.yaml).
const client = createApiClient<paths>();

export async function listSignals() {
  return unwrap(await client.GET("/api/v1/signals"));
}

export async function getSignal(intersectionId: string) {
  return unwrap(
    await client.GET("/api/v1/signals/{intersection_id}", {
      params: { path: { intersection_id: intersectionId } },
    }),
  );
}

export async function listSignalCommands(
  intersectionId: string,
  query?: Query<operations["listSignalCommands"]>,
) {
  return unwrap(
    await client.GET("/api/v1/signals/{intersection_id}/commands", {
      params: { path: { intersection_id: intersectionId }, query },
    }),
  );
}

export async function sendSignalCommand(
  intersectionId: string,
  command: JsonBody<operations["sendSignalCommand"]>,
) {
  return unwrap(
    await client.POST("/api/v1/signals/{intersection_id}/commands", {
      params: { path: { intersection_id: intersectionId } },
      body: command,
    }),
  );
}
