import { APPROACHES, STATES, type SegmentState } from "./types";

/**
 * Le seul fichier qui appelle le réseau (règle de lint). Garde-fous de l'ADR-030 :
 * - une seule route, `GET /api/v1/public/congestion`, sans jeton ni cookie (`credentials: "omit"`) ;
 * - la réponse est vérifiée champ par champ : un champ manquant ou inconnu est une erreur, pas une donnée.
 */
export const CONGESTION_PATH = "/api/v1/public/congestion";

export type ErrorKind = "reseau" | "limite" | "indisponible" | "inattendue" | "format";

export class ApiError extends Error {
  constructor(
    readonly kind: ErrorKind,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FIELDS = [
  "road_segment_id",
  "intersection_id",
  "approach",
  "state",
  "updated_at",
  "simulated",
];

function isSegment(value: unknown): value is SegmentState {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  const keys = Object.keys(item);
  return (
    keys.length === FIELDS.length &&
    FIELDS.every((field) => field in item) &&
    typeof item.road_segment_id === "string" &&
    typeof item.intersection_id === "string" &&
    (APPROACHES as readonly unknown[]).includes(item.approach) &&
    (STATES as readonly unknown[]).includes(item.state) &&
    typeof item.updated_at === "string" &&
    !Number.isNaN(new Date(item.updated_at).getTime()) &&
    typeof item.simulated === "boolean"
  );
}

export async function fetchCongestion(signal?: AbortSignal, baseUrl = ""): Promise<SegmentState[]> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${CONGESTION_PATH}`, {
      method: "GET",
      credentials: "omit",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("reseau", "Le réseau ne répond pas.");
  }
  if (response.status === 429) throw new ApiError("limite", "Trop de demandes.");
  if (response.status >= 500 || response.status === 404) {
    throw new ApiError("indisponible", "Le service est indisponible.");
  }
  if (!response.ok) throw new ApiError("inattendue", `Réponse inattendue (${response.status}).`);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("format", "Réponse illisible.");
  }
  const items = (body as { items?: unknown } | null)?.items;
  if (typeof body !== "object" || body === null || Object.keys(body).length !== 1) {
    throw new ApiError("format", "Réponse inattendue.");
  }
  if (!Array.isArray(items) || !items.every(isSegment)) {
    throw new ApiError("format", "Réponse inattendue.");
  }
  return items;
}
