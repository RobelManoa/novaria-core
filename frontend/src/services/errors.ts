import type { components } from "@/types/api/api-metier";

/** Corps d'erreur unique de l'API (`application/problem+json`, RFC 9457), défini dans contracts/openapi/common.yaml. */
export type Problem = components["schemas"]["Problem"];

/** Codes du contrat, plus deux codes propres au client : réseau coupé et réponse inattendue. */
export type ErrorCode = Problem["code"] | "NETWORK_ERROR" | "UNEXPECTED_RESPONSE";

/**
 * Message affiché à l'utilisateur pour chaque code. Le type `Record<ErrorCode, string>` rend la liste
 * exhaustive : un code ajouté au contrat ne compile plus tant qu'on n'a pas écrit son message.
 */
const MESSAGES: Record<ErrorCode, string> = {
  UNAUTHENTICATED: "Votre session a expiré. Reconnectez-vous.",
  INVALID_CREDENTIALS: "Identifiant ou mot de passe incorrect.",
  FORBIDDEN: "Votre rôle ne permet pas cette action.",
  NOT_FOUND: "Élément introuvable.",
  CONFLICT: "Cette opération entre en conflit avec l'état actuel.",
  VALIDATION_ERROR: "Certaines valeurs sont invalides.",
  INVALID_STATE_TRANSITION: "Cette alerte ne peut pas passer dans cet état.",
  COMMAND_IN_PROGRESS: "Une commande est déjà en cours pour ce carrefour.",
  UNSAFE_COMMAND: "Commande refusée : elle ne respecte pas les règles de sécurité des feux.",
  RATE_LIMITED: "Trop de requêtes. Réessayez dans un instant.",
  FORECAST_UNAVAILABLE: "Aucune prévision n'est disponible pour le moment.",
  UPSTREAM_UNAVAILABLE: "Un service est momentanément indisponible. Réessayez dans un instant.",
  INTERNAL_ERROR: "Une erreur est survenue côté serveur.",
  NETWORK_ERROR: "Le serveur est injoignable. Vérifiez la connexion.",
  UNEXPECTED_RESPONSE: "La réponse du serveur est inattendue.",
};

/** Code déduit du statut HTTP quand le corps n'est pas un `Problem` (passerelle, proxy, panne). */
function codeFromStatus(status: number): ErrorCode {
  switch (status) {
    case 401:
      return "UNAUTHENTICATED";
    case 403:
      return "FORBIDDEN";
    case 404:
      return "NOT_FOUND";
    case 409:
      return "CONFLICT";
    case 422:
      return "VALIDATION_ERROR";
    case 429:
      return "RATE_LIMITED";
    case 502:
    case 503:
    case 504:
      return "UPSTREAM_UNAVAILABLE";
    default:
      return status >= 500 ? "INTERNAL_ERROR" : "UNEXPECTED_RESPONSE";
  }
}

function isProblem(value: unknown): value is Problem {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.status === "number";
}

/** Seule erreur que les appels d'API lèvent : toute défaillance (HTTP ou réseau) arrive sous cette forme. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  /** Identifiant à citer dans un signalement ; absent si le serveur n'a pas répondu. */
  readonly correlationId: string | null;
  /** Un élément par champ invalide (`VALIDATION_ERROR`). */
  readonly fieldErrors: ReadonlyArray<{ field: string; message: string }>;

  constructor(init: {
    status: number;
    code: ErrorCode;
    detail?: string;
    correlationId?: string | null;
    fieldErrors?: ReadonlyArray<{ field: string; message: string }>;
  }) {
    super(init.detail ?? MESSAGES[init.code]);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.correlationId = init.correlationId ?? null;
    this.fieldErrors = init.fieldErrors ?? [];
  }

  /** Construit l'erreur d'une réponse HTTP en échec, avec ou sans corps `Problem`. */
  static async fromResponse(response: Response, correlationId?: string): Promise<ApiError> {
    let body: unknown = null;
    try {
      body = JSON.parse(await response.clone().text());
    } catch {
      // corps vide ou non JSON : on se rabat sur le statut
    }
    const headerId = response.headers.get("x-correlation-id");
    if (isProblem(body)) {
      return new ApiError({
        status: response.status,
        code: body.code,
        detail: body.detail,
        correlationId: body.correlation_id ?? headerId ?? correlationId,
        fieldErrors: body.errors,
      });
    }
    return new ApiError({
      status: response.status,
      code: codeFromStatus(response.status),
      correlationId: headerId ?? correlationId,
    });
  }

  static network(cause: unknown, correlationId?: string): ApiError {
    const error = new ApiError({ status: 0, code: "NETWORK_ERROR", correlationId });
    error.cause = cause;
    return error;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** Phrase à montrer à l'utilisateur, en français, quelle que soit l'erreur reçue. */
export function messageFor(error: unknown): string {
  if (isApiError(error)) return MESSAGES[error.code];
  return MESSAGES.UNEXPECTED_RESPONSE;
}
