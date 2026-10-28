import type { components, paths } from "@/types/api/api-metier";
import { createApiClient, unwrap } from "./client";

export type Health = components["schemas"]["Health"];

// La sonde de santé est la même pour tous les services : la passerelle l'envoie à l'API métier.
const client = createApiClient<paths>();

export async function getHealth(): Promise<Health> {
  return unwrap(await client.GET("/api/v1/health"));
}
