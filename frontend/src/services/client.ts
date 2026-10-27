import createClient, { type Middleware } from "openapi-fetch";
import { ApiError } from "./errors";
import { clearSession, getAccessToken } from "./session";

/**
 * Les chemins du contrat commencent par `/api/v1` : on appelle l'origine de la page (proxy de Vite ou
 * nginx). Un `Request` exige une URL absolue, d'où l'origine plutôt qu'une chaîne vide.
 */
const BASE_URL = globalThis.location?.origin ?? "";

function newCorrelationId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

/** Les identifiants de corrélation des requêtes en cours, pour rattacher une erreur réseau à sa requête. */
const correlationIds = new WeakMap<Request, string>();

/**
 * Traitement commun à tous les appels : jeton, identifiant de corrélation, et conversion de toute
 * défaillance en `ApiError`. Aucune autre partie du code ne lit une réponse en échec.
 */
const middleware: Middleware = {
  onRequest({ request }) {
    const correlationId = newCorrelationId();
    correlationIds.set(request, correlationId);
    request.headers.set("X-Correlation-ID", correlationId);
    const token = getAccessToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  async onResponse({ request, response }) {
    if (response.ok) return response;
    const error = await ApiError.fromResponse(response, correlationIds.get(request));
    // Jeton refusé ou expiré : la session se ferme ici, une seule fois, et l'interface revient à la connexion.
    if (error.code === "UNAUTHENTICATED") clearSession();
    throw error;
  },
  onError({ request, error }) {
    return error instanceof ApiError ? error : ApiError.network(error, correlationIds.get(request));
  },
};

/** Client typé par les chemins d'un contrat : `createApiClient<paths>()` avec `paths` de src/types/api/<service>.ts. */
export function createApiClient<Paths extends object>() {
  // `fetch` est relu à chaque appel : les tests et les extensions peuvent le remplacer après la création.
  const client = createClient<Paths>({
    baseUrl: BASE_URL,
    fetch: (request) => globalThis.fetch(request),
  });
  client.use(middleware);
  return client;
}

/** Données d'une réponse réussie ; une réponse sans corps là où le contrat en promet un est une erreur. */
export function unwrap<T>(result: { data?: T }): T {
  if (result.data === undefined) {
    throw new ApiError({ status: 200, code: "UNEXPECTED_RESPONSE" });
  }
  return result.data;
}

/** Paramètres de requête d'une opération du contrat. */
export type Query<Operation> = Operation extends { parameters: { query?: infer Q } } ? Q : never;

/** Corps JSON d'une opération du contrat. */
export type JsonBody<Operation> = Operation extends { requestBody?: infer B }
  ? NonNullable<B> extends { content: { "application/json": infer Json } }
    ? Json
    : never
  : never;
