import type { operations, paths } from "@/types/api/traitement";
import { createApiClient, unwrap, type Query } from "./client";

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
