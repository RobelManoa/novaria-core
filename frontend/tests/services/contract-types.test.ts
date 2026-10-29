import { describe, expectTypeOf, it } from "vitest";
import type { Health } from "@/services/api";
import type { ErrorCode, Problem } from "@/services/errors";
import { listIndicators } from "@/services/traitement";
import type { operations } from "@/types/api/traitement";

// Ces vérifications se jouent à la compilation (`npm run build`, éditeur) : elles épinglent ce que
// l'interface consomme. Si un contrat retire ou renomme un de ces éléments, `tsc` signale l'écart.
describe("ce que l'interface attend du contrat", () => {
  it("la sonde de santé porte les quatre champs affichés par ApiStatus", () => {
    expectTypeOf<Health>().toHaveProperty("status").toBeString();
    expectTypeOf<Health>().toHaveProperty("version").toBeString();
    expectTypeOf<Health>().toHaveProperty("revision").toBeString();
    expectTypeOf<Health>().toHaveProperty("environment").toBeString();
  });

  it("une erreur porte un code, un statut et un identifiant de corrélation", () => {
    expectTypeOf<Problem>().toHaveProperty("code");
    expectTypeOf<Problem>().toHaveProperty("status").toBeNumber();
    expectTypeOf<Problem>().toHaveProperty("correlation_id").toBeString();
    expectTypeOf<Problem["code"]>().toExtend<ErrorCode>();
  });

  it("les indicateurs se filtrent par état de congestion et par tronçon", () => {
    type Filtres = NonNullable<Parameters<typeof listIndicators>[0]>;
    expectTypeOf<Filtres>().toHaveProperty("congestion_state");
    expectTypeOf<Filtres>().toHaveProperty("road_segment_id");
    expectTypeOf<operations["listIndicators"]>().toHaveProperty("responses");
  });
});
