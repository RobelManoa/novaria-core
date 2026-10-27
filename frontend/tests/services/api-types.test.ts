// @vitest-environment node
import { describe, expect, it } from "vitest";
import { SERVICES, exposedContracts, outOfDate } from "../../scripts/api-types.mjs";

describe("types d'API générés depuis contracts/openapi/", () => {
  it("correspondent aux contrats (sinon : npm run api:generate)", async () => {
    const perimes = await outOfDate();
    expect(perimes, "Contrat modifié sans régénérer : lancer « npm run api:generate »").toEqual([]);
  }, 60_000);

  it("couvrent chaque contrat exposé par la passerelle", async () => {
    // collecte reste sur le réseau interne : le tableau de bord ne l'appelle jamais
    expect([...SERVICES].sort()).toEqual((await exposedContracts()).sort());
  });
});
