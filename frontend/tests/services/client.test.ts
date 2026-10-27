import { afterEach, describe, expect, it, vi } from "vitest";
import { getHealth } from "@/services/api";
import { ApiError, isApiError, messageFor, type ErrorCode } from "@/services/errors";
import { setAccessToken } from "@/services/session";

const problem = (overrides: Record<string, unknown> = {}) => ({
  type: "https://novaria.local/problems/validation-error",
  title: "Requête invalide",
  status: 422,
  code: "VALIDATION_ERROR",
  detail: "Le paramètre limit doit être compris entre 1 et 500.",
  correlation_id: "corr-serveur",
  errors: [{ field: "query.limit", message: "doit être au plus 500" }],
  ...overrides,
});

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  const text = body === null ? "" : typeof body === "string" ? body : JSON.stringify(body);
  return new Response(text, { status, headers });
}

async function failure(): Promise<ApiError> {
  const error = await getHealth().then(
    () => null,
    (e: unknown) => e,
  );
  expect(isApiError(error)).toBe(true);
  return error as ApiError;
}

describe("gestion unique des erreurs", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setAccessToken(null);
  });

  it("convertit un corps application/problem+json en ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      respond(422, problem(), { "content-type": "application/problem+json" }),
    );
    const error = await failure();
    expect(error).toBeInstanceOf(Error);
    expect(error).toMatchObject({
      name: "ApiError",
      status: 422,
      code: "VALIDATION_ERROR",
      correlationId: "corr-serveur",
      message: "Le paramètre limit doit être compris entre 1 et 500.",
      fieldErrors: [{ field: "query.limit", message: "doit être au plus 500" }],
    });
  });

  it.each([
    [401, "UNAUTHENTICATED"],
    [403, "FORBIDDEN"],
    [404, "NOT_FOUND"],
    [409, "CONFLICT"],
    [422, "VALIDATION_ERROR"],
    [429, "RATE_LIMITED"],
    [502, "UPSTREAM_UNAVAILABLE"],
    [503, "UPSTREAM_UNAVAILABLE"],
    [504, "UPSTREAM_UNAVAILABLE"],
    [500, "INTERNAL_ERROR"],
    [418, "UNEXPECTED_RESPONSE"],
  ] satisfies Array<[number, ErrorCode]>)(
    "déduit le code du statut %i quand le corps n'est pas un Problem",
    async (status, code) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(respond(status, "<html>passerelle</html>"));
      const error = await failure();
      expect(error).toMatchObject({ status, code, fieldErrors: [] });
    },
  );

  it("ignore un corps JSON qui n'est pas un Problem", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(respond(503, {}));
    expect(await failure()).toMatchObject({ status: 503, code: "UPSTREAM_UNAVAILABLE" });
  });

  it("transforme une coupure réseau en NETWORK_ERROR, sans statut", async () => {
    const cause = new TypeError("Failed to fetch");
    const spy = vi.spyOn(globalThis, "fetch").mockRejectedValue(cause);
    const error = await failure();
    expect(error).toMatchObject({ status: 0, code: "NETWORK_ERROR", cause });
    const sent = (spy.mock.calls[0][0] as Request).headers.get("X-Correlation-ID");
    expect(error.correlationId).toBe(sent);
  });

  it("garde l'identifiant de corrélation envoyé quand le serveur n'en renvoie aucun", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(respond(500, null));
    const error = await failure();
    const sent = (spy.mock.calls[0][0] as Request).headers.get("X-Correlation-ID");
    expect(sent).toBeTruthy();
    expect(error.correlationId).toBe(sent);
  });

  it("préfère l'identifiant de corrélation de la réponse à celui de la requête", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      respond(500, null, { "X-Correlation-ID": "corr-en-tete" }),
    );
    expect((await failure()).correlationId).toBe("corr-en-tete");
  });

  it("signale une réponse réussie sans corps comme inattendue", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    expect(await failure()).toMatchObject({ code: "UNEXPECTED_RESPONSE" });
  });
});

describe("requêtes envoyées", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setAccessToken(null);
  });

  it("n'envoie pas de jeton sans session, et l'envoie ensuite", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => respond(200, {}));
    await getHealth();
    expect((spy.mock.calls[0][0] as Request).headers.get("Authorization")).toBeNull();

    setAccessToken("jeton-de-test");
    await getHealth();
    expect((spy.mock.calls[1][0] as Request).headers.get("Authorization")).toBe(
      "Bearer jeton-de-test",
    );

    setAccessToken(null);
    await getHealth();
    expect((spy.mock.calls[2][0] as Request).headers.get("Authorization")).toBeNull();
  });

  it("envoie un identifiant de corrélation différent à chaque requête", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => respond(200, {}));
    await getHealth();
    await getHealth();
    const ids = spy.mock.calls.map(([request]) =>
      (request as Request).headers.get("X-Correlation-ID"),
    );
    expect(ids[0]).toBeTruthy();
    expect(ids[0]).not.toBe(ids[1]);
  });
});

describe("messageFor", () => {
  it("donne une phrase en français pour une ApiError", () => {
    expect(messageFor(new ApiError({ status: 401, code: "UNAUTHENTICATED" }))).toBe(
      "Votre session a expiré. Reconnectez-vous.",
    );
    expect(messageFor(new ApiError({ status: 0, code: "NETWORK_ERROR" }))).toContain("injoignable");
  });

  it("ne révèle pas le détail du serveur dans la phrase affichée", () => {
    const error = new ApiError({ status: 500, code: "INTERNAL_ERROR", detail: "trace interne" });
    expect(messageFor(error)).not.toContain("trace interne");
  });

  it("traite toute autre erreur comme une réponse inattendue", () => {
    expect(messageFor(new Error("boom"))).toBe("La réponse du serveur est inattendue.");
    expect(messageFor("texte")).toBe("La réponse du serveur est inattendue.");
  });
});
