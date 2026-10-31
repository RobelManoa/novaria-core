import type { components, operations, paths } from "@/types/api/traitement";
import { createApiClient, unwrap, type Query } from "./client";

export type Indicator = components["schemas"]["Indicator"];
export type CongestionState = components["schemas"]["CongestionState"];
export type SourceType = components["schemas"]["SourceType"];

// Traitement : référentiel, indicateurs, prévisions (contracts/openapi/traitement.openapi.yaml).
const client = createApiClient<paths>();

export async function listIntersections(query?: Query<operations["listIntersections"]>) {
  return unwrap(await client.GET("/api/v1/intersections", { params: { query } }));
}

export async function getIntersection(intersectionId: string) {
  return unwrap(
    await client.GET("/api/v1/intersections/{intersection_id}", {
      params: { path: { intersection_id: intersectionId } },
    }),
  );
}

export async function listRoadSegments(query?: Query<operations["listRoadSegments"]>) {
  return unwrap(await client.GET("/api/v1/road-segments", { params: { query } }));
}

export async function listIndicators(query?: Query<operations["listIndicators"]>) {
  return unwrap(await client.GET("/api/v1/indicators", { params: { query } }));
}

/**
 * Lit les pages d'indicateurs l'une après l'autre (curseur `next_cursor`) jusqu'à la dernière, ou jusqu'à
 * `maxPages`. L'API trie du plus récent au plus ancien : une lecture tronquée perd les fenêtres les plus
 * anciennes, et `truncated` le dit.
 */
export async function listAllIndicators(
  query: Omit<Query<operations["listIndicators"]>, "cursor">,
  maxPages: number,
): Promise<{ items: Indicator[]; truncated: boolean }> {
  const items: Indicator[] = [];
  let cursor: string | undefined;
  for (let pageNumber = 0; pageNumber < maxPages; pageNumber += 1) {
    const page = await listIndicators({ ...query, cursor });
    items.push(...page.items);
    if (page.next_cursor === null) return { items, truncated: false };
    cursor = page.next_cursor;
  }
  return { items, truncated: true };
}

export async function listLatestIndicators(query?: Query<operations["listLatestIndicators"]>) {
  return unwrap(await client.GET("/api/v1/indicators/latest", { params: { query } }));
}

export async function getIndicator(indicatorId: string) {
  return unwrap(
    await client.GET("/api/v1/indicators/{indicator_id}", {
      params: { path: { indicator_id: indicatorId } },
    }),
  );
}

export async function listForecasts(query: Query<operations["listForecasts"]>) {
  return unwrap(await client.GET("/api/v1/forecasts", { params: { query } }));
}
