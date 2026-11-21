import { describe, expect, it } from "vitest";
import { LIEUX, TRONCONS, nomDuLieu, nomDuTroncon, tousLesLieux } from "../src/lieux";
import { TRAJETS_PROPOSES } from "../src/trajets";

describe("les noms que lit un citoyen", () => {
  it("les 24 tronçons du réseau ont chacun un nom, tous différents", () => {
    expect(TRONCONS).toHaveLength(24);
    const noms = TRONCONS.map(nomDuTroncon);
    expect(new Set(noms).size).toBe(24);
  });

  it("aucun nom ne contient un code du système", () => {
    for (const nom of [...Object.values(LIEUX), ...TRONCONS.map(nomDuTroncon)]) {
      expect(nom).not.toMatch(/ROAD|INT_|\d{3}|_/);
    }
  });

  it("écrit « Lieu, en venant du côté »", () => {
    expect(nomDuTroncon("ROAD_001")).toBe("Place de la Gare, en venant du nord");
    expect(nomDuTroncon("ROAD_004")).toBe("Place de la Gare, en venant de l'ouest");
    expect(nomDuTroncon("ROAD_024")).toBe("Chemin des Vergers, en venant de l'ouest");
    expect(nomDuLieu("ROAD_010")).toBe("Rue du Marché");
  });

  it("un tronçon inconnu n'est jamais montré par son code", () => {
    for (const id of ["ROAD_025", "ROAD_000", "x", "", "ROAD_1"]) {
      expect(nomDuTroncon(id)).toBe("Un tronçon inconnu");
      expect(nomDuLieu(id)).toBe("Un lieu inconnu");
    }
  });

  it("la liste du choix rend six lieux de quatre tronçons, dans l'ordre", () => {
    const lieux = tousLesLieux();
    expect(lieux).toHaveLength(6);
    expect(lieux.every((l) => l.troncons.length === 4)).toBe(true);
    expect(lieux.flatMap((l) => l.troncons.map((t) => t.id))).toEqual([...TRONCONS]);
  });

  it("les trajets proposés ne citent que des tronçons qui existent", () => {
    for (const trajet of TRAJETS_PROPOSES) {
      expect(trajet.troncons.length).toBeGreaterThanOrEqual(1);
      for (const id of trajet.troncons) expect(TRONCONS).toContain(id);
    }
  });
});
